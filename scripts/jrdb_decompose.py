# -*- coding: utf-8 -*-
"""A×B分解 + confirmed_odds分母
修正版(softmax正規化修正済み)の三連単・三連複について:

回収率 = A × B
A = Σ_hit(est_odds×100) / (n×100) = 推定オッズでの回収率
B = Σ_hit(actual_payout) / Σ_hit(est_odds×100) = 実/推定比

+ confirmed_odds分母: EV = model_prob × confirmed_odds での回収率
+ tau=0コントロール
+ 上位10的中除外
+ P_model vs 的中率キャリブレーション
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations, permutations
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')
DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
db = sqlite3.connect(DB, timeout=30)
print("Loading...", flush=True)

races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid, _, _, _, _ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?', (rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]: {'hid':e[1],'jockey':e[2],'trainer':e[3],'idm':e[4],'total':e[5],'rider':e[6],'run_style':e[7],'weight':e[8]} for e in es}
result_cache = defaultdict(list)
result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3]})
    result_full[row[0]][row[1]] = row[2]
race_horses = {}
for rid,_,_,_,_ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?',(rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)
ts_odds = {}
for mb in [0,1,2,3,5,10]:
    ts_odds[mb] = defaultdict(dict)
    for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=? AND odds>0',(mb,)).fetchall():
        ts_odds[mb][rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
# confirmed_odds (sanrentan)
confirmed_st = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM confirmed_odds WHERE bet_type='sanrentan' AND odds>0").fetchall():
    confirmed_st[row[0]][row[1]] = row[2]
confirmed_tr = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM confirmed_odds WHERE bet_type='sanrenpuku' AND odds>0").fetchall():
    confirmed_tr[row[0]][row[1]] = row[2]
cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB,'CYB','*.txt'))):
    with open(fpath,'rb') as f:
        for line in f.readlines():
            if len(line)<38: continue
            raw=line.decode('ascii','replace')
            rid2=f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
            try: hn_i=int(raw[8:10]); score=int(raw[33:35].strip())
            except: continue
            cyb_cache[(rid2,hn_i)] = score
db.close()
print(f"Loaded. confirmed_st: {sum(len(v) for v in confirmed_st.values()):,}, confirmed_tr: {sum(len(v) for v in confirmed_tr.values()):,}", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
TAKEOUT = {'sanrenpuku':0.25,'sanrentan':0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_full(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3; S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float); trifecta={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2); d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3); trio[tuple(sorted([i,j,k]))]+=pijk; trifecta[(i,j,k)]=pijk
    return trio, trifecta

print("Building...", flush=True)
js={}; hh={}; ts_st={}
datasets = {'sanrenpuku':{},'sanrentan':{}}
FNAMES = {}

for rid,rd,vc,sf,dt in races_raw:
    year=int(rd[:4])
    def do_update():
        for res in result_cache.get(rid,[]):
            hn,fp,hid=res['hn'],res['fp'],res['hid']
            ent=entry_cache.get(rid,{}).get(hn,{})
            jn=ent.get('jockey',''); tn=ent.get('trainer','')
            if jn:
                if jn not in js: js[jn]={'r':0,'w':0,'t3':0}
                js[jn]['r']+=1
                if fp==1: js[jn]['w']+=1
                if fp<=3: js[jn]['t3']+=1
            if tn:
                if tn not in ts_st: ts_st[tn]={'r':0,'w':0,'t3':0}
                ts_st[tn]['r']+=1
                if fp==1: ts_st[tn]['w']+=1
                if fp<=3: ts_st[tn]['t3']+=1
            if hid:
                if hid not in hh: hh[hid]=[]
                hh[hid].append({'fp':fp,'dist':dt,'surface':sf})
                if len(hh[hid])>30: hh[hid]=hh[hid][-30:]
    if year<2022: do_update(); continue
    hl=race_horses.get(rid,[])
    if len(hl)<5: do_update(); continue
    rl=result_cache.get(rid,[])
    if not rl: do_update(); continue
    winners=[r['hn'] for r in rl if r['fp']==1]
    if not winners or winners[0] not in hl: do_update(); continue
    o3=ts_odds[3].get(rid,{}); o5=ts_odds[5].get(rid,{})
    odds_mkt=o3 if len(o3)>=len(hl)*0.8 else sed.get(rid,{})
    has_move=len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
    entries=entry_cache.get(rid,{}); n=len(hl)
    inv_arr=np.array([1/odds_mkt.get(h,999) for h in hl]); s=inv_arr.sum()
    if s==0: do_update(); continue
    mp=inv_arr/s; mp=mp**1.015; mp/=mp.sum()
    idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
    riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
    ozd=oz_cache.get(rid,{}); mkt_d=odds_mkt
    oz_inv={h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
    mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
    oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
    cyb_scores=[cyb_cache.get((rid,h),0) for h in hl]
    avg_cyb=np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0
    trio_mkt,trifecta_mkt=sh_full(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1]); rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    top1_idx=np.argmax(mp)
    feats_h={}
    for i,h in enumerate(hl):
        ent=entries.get(h,{}); f={}
        f['idm_c']=(ent.get('idm') or 50)-avg_idm; f['rider_c']=(ent.get('rider') or 0)-avg_rider
        f['total_index']=ent.get('total') or 0
        oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
        f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
        f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
        jn=ent.get('jockey',''); tn=ent.get('trainer','')
        jst=js.get(jn,{}); f['jockey_t3rate']=jst.get('t3',0)/jst['r'] if jst.get('r',0)>=30 else -1
        tst=ts_st.get(tn,{}); f['trainer_t3rate']=tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
        runs=hh.get(ent.get('hid',''),[])
        f['horse_runs']=len(runs)
        if runs:
            rc=runs[-5:]; f['avg_fp_5']=np.mean([r['fp'] for r in rc])
            f['top3_rate']=sum(1 for r in runs if r['fp']<=3)/len(runs)
            f['last_fp']=runs[-1]['fp']; f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
        else: f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        f['win_odds_3min']=o3.get(h,0); feats_h[h]=f
    top8=[h for h,_ in sorted(odds_mkt.items(),key=lambda x:x[1])[:8]] if odds_mkt else hl[:8]
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    def make_trio(a,b,c):
        pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1,v2,v3=f1.get(k,0),f2.get(k,0),f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        ol=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=ol[0]/ol[-1] if len(ol)>=2 and ol[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in ol if o>0)
        return pf

    # 三連複
    if len(top3_fps)>=3:
        ds=datasets['sanrenpuku']
        if year not in ds: ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[],'confirmed':[]}
        wtr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        for a,b,c in combinations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c])); pf=make_trio(a,b,c)
            if 'sanrenpuku' not in FNAMES: FNAMES['sanrenpuku']=sorted(pf.keys())
            ds[year]['X'].append([pf.get(k,0) for k in FNAMES['sanrenpuku']])
            ds[year]['y'].append(1 if combo==wtr else 0)
            ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            ds[year]['meta'].append((rid,combo)); ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrenpuku']))
            ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            ds[year]['sh_prob'].append(float(sh_p))
            ds[year]['confirmed'].append(confirmed_tr.get(rid,{}).get(combo,0))

    # 三連単
    if len(top3_fps)>=3:
        ds=datasets['sanrentan']
        if year not in ds: ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[],'confirmed':[]}
        wst=f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        for a,b,c in permutations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            if top1_idx not in (ai,bi,ci): continue
            sh_p=trifecta_mkt.get((ai,bi,ci),0)
            if sh_p<=0: continue
            combo=f'{a}-{b}-{c}'; pf=make_trio(a,b,c)
            pf['first_prob']=mp[ai]; pf['second_prob']=mp[bi]; pf['third_prob']=mp[ci]
            if 'sanrentan' not in FNAMES: FNAMES['sanrentan']=sorted(pf.keys())
            ds[year]['X'].append([pf.get(k,0) for k in FNAMES['sanrentan']])
            ds[year]['y'].append(1 if combo==wst else 0)
            ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            ds[year]['meta'].append((rid,combo)); ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrentan']))
            ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            ds[year]['sh_prob'].append(float(sh_p))
            ds[year]['confirmed'].append(confirmed_st.get(rid,{}).get(combo,0))
    do_update()

for bt in datasets:
    for y in sorted(datasets[bt].keys()):
        d=datasets[bt][y]
        d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        d['sh_prob']=np.array(d['sh_prob']); d['pop']=np.array(d['pop'])
        d['confirmed']=np.array(d['confirmed'])
    sizes=', '.join(f'{y}:{len(datasets[bt][y]["X"])}' for y in sorted(datasets[bt].keys()))
    print(f"  {bt}: {sizes}")

lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(ds, fnames, params, hjc_type, force_tau0=False):
    """修正版WF: A/B分解用のデータを全部返す"""
    all_bets=[]
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in ds]; fit_yr=test_yr-1
        if not train_yrs or fit_yr not in ds or test_yr not in ds: continue
        X_tr=np.vstack([ds[y]['X'] for y in train_yrs]); y_tr=np.concatenate([ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([ds[y]['init'] for y in train_yrs])
        model=lgb.train(params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
        X_f=ds[fit_yr]['X']; y_f=ds[fit_yr]['y']; init_f=ds[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True); rd_f=defaultdict(list)
        for i,m in enumerate(ds[fit_yr]['meta']): rd_f[m[0]].append(i)
        if not force_tau0:
            def neg_ll(p):
                b,tau=p; nll=0; nr=0
                for rid2,idxs in rd_f.items():
                    ys=y_f[idxs]; wi=np.where(ys==1)[0]
                    if len(wi)==0: continue
                    s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                    nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
                return nll/nr if nr>0 else 999
            res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000}); b_use,tau_use=res.x
        else: b_use,tau_use=1.0,0.0
        print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")

        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; odds_te=ds[test_yr]['odds']
        sh_te=ds[test_yr]['sh_prob']; conf_te=ds[test_yr]['confirmed']
        pop_te=ds[test_yr]['pop']
        raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs_rel=np.exp(s)/np.exp(s).sum()
            sh_sum=sh_te[idxs].sum()
            probs=probs_rel*sh_sum  # FIX: absolute prob
            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; est_o=odds_te[idx]; sh_p=sh_te[idx]
                ev=probs[j]*est_o; is_hit=y_te[idx]
                payout_hjc=hjc_all.get(rid2,{}).get(hjc_type,{}).get(str(combo) if isinstance(combo,int) else combo,0) if is_hit else 0
                conf_o=conf_te[idx]
                all_bets.append({
                    'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                    'payout_hjc':payout_hjc,'est_odds':float(est_o),'sh_prob':float(sh_p),
                    'model_prob':float(probs[j]),'confirmed_odds':float(conf_o),
                    'pop':int(pop_te[idx]),'combo':combo,
                })
    return all_bets

print("\nRunning WF...", flush=True)
bt = run_wf(datasets['sanrenpuku'],FNAMES['sanrenpuku'],lgb_p,'sanrenpuku_hjc')
bs = run_wf(datasets['sanrentan'],FNAMES['sanrentan'],lgb_p,'sanrentan_hjc')
bt_t0 = run_wf(datasets['sanrenpuku'],FNAMES['sanrenpuku'],lgb_p,'sanrenpuku_hjc',force_tau0=True)
bs_t0 = run_wf(datasets['sanrentan'],FNAMES['sanrentan'],lgb_p,'sanrentan_hjc',force_tau0=True)

def decompose(label, bets, ev_th=1.2):
    sub = [b for b in bets if b['ev']>=ev_th]
    if len(sub)<10:
        print(f"  {label}: n={len(sub)} (insufficient)")
        return
    n=len(sub); hits=[b for b in sub if b['is_hit']]
    nh=len(hits)
    invest=n*100

    # A: 推定オッズでの回収率
    sum_est_hit = sum(b['est_odds']*100 for b in hits)
    A = sum_est_hit / invest if invest>0 else 0

    # B: 実/推定比 (HJC)
    sum_hjc_hit = sum(b['payout_hjc']*100 for b in hits)
    B = sum_hjc_hit / sum_est_hit if sum_est_hit>0 else 0

    rec_est = A * 100  # 推定オッズでの回収率%
    rec_hjc = A * B * 100  # HJC実回収率%

    # confirmed_odds分母
    has_conf = sum(1 for b in sub if b['confirmed_odds']>0)
    if has_conf > 0:
        # confirmed分母でEV再計算
        sub_conf = [b for b in sub if b['confirmed_odds']>0]
        ev_conf = [b['model_prob']*b['confirmed_odds'] for b in sub_conf]
        sub_conf_ev = [b for b,e in zip(sub_conf, ev_conf) if e>=ev_th]
        n_conf=len(sub_conf_ev)
        if n_conf>0:
            inv_conf=n_conf*100
            pay_conf=sum(b['payout_hjc']*100 for b in sub_conf_ev if b['is_hit'])
            rec_conf=pay_conf/inv_conf*100 if inv_conf>0 else 0
        else: rec_conf=0; n_conf=0
    else: rec_conf=0; n_conf=0

    # 上位10的中除外
    hits_sorted = sorted(hits, key=lambda x:-x['payout_hjc'])
    if len(hits_sorted)>10:
        top10_payout = sum(b['payout_hjc']*100 for b in hits_sorted[:10])
        rest_payout = sum_hjc_hit - top10_payout
        rec_ex10 = rest_payout / invest * 100
    else: rec_ex10 = 0

    # 平均値
    avg_est = np.mean([b['est_odds'] for b in hits]) if hits else 0
    avg_hjc = np.mean([b['payout_hjc'] for b in hits]) if hits else 0
    avg_conf = np.mean([b['confirmed_odds'] for b in hits if b['confirmed_odds']>0]) if hits else 0

    print(f"\n  === {label} (EV>={ev_th}) ===")
    print(f"  n={n:,}, hits={nh}, hit_rate={100*nh/n:.3f}%")
    print(f"  A (est_odds rec): {rec_est:.1f}%")
    print(f"  B (HJC/est ratio): {B:.3f}")
    print(f"  A×B (HJC rec):     {rec_hjc:.1f}%")
    print(f"  confirmed分母:     {rec_conf:.1f}% (n={n_conf:,})")
    print(f"  上位10的中除外:    {rec_ex10:.1f}%")
    print(f"  avg est_odds(hit): {avg_est:.1f}x")
    print(f"  avg HJC(hit):      {avg_hjc:.1f}x")
    print(f"  avg confirmed(hit):{avg_conf:.1f}x")
    if hits_sorted:
        top5_str = ', '.join(str(round(b['payout_hjc'])) + 'x' for b in hits_sorted[:5])
        print(f"  top5 HJC payouts:  {top5_str}")
        top10_share = sum(b['payout_hjc'] for b in hits_sorted[:10]) / sum(b['payout_hjc'] for b in hits) * 100 if hits else 0
        print(f"  top10 share:       {top10_share:.1f}%")

    # 年別
    for yr in [2024,2025,2026]:
        ys=[b for b in sub if b['year']==yr]
        if not ys: continue
        ny=len(ys); hy=sum(1 for b in ys if b['is_hit'])
        inv_y=ny*100; pay_y=sum(b['payout_hjc']*100 for b in ys if b['is_hit'])
        rec_y=pay_y/inv_y*100 if inv_y>0 else 0
        hits_y=[b for b in ys if b['is_hit']]
        sum_est_y=sum(b['est_odds']*100 for b in hits_y)
        A_y=sum_est_y/inv_y if inv_y>0 else 0
        B_y=pay_y/sum_est_y if sum_est_y>0 else 0
        print(f"  {yr}: n={ny:,} hit={hy} A={A_y*100:.1f}% B={B_y:.3f} rec={rec_y:.1f}%")

# === Results ===
print(f"\n{'='*100}")
print("A×B分解 + confirmed分母 + 上位除外")
print(f"{'='*100}")

for ev_th in [1.0, 1.2]:
    decompose(f"三連複 1fav", [b for b in bt if b['pop']<=1], ev_th)
    decompose(f"三連複 全", bt, ev_th)
    decompose(f"三連単 1fav", bs, ev_th)  # already filtered by top1
    decompose(f"三連複 tau=0 1fav", [b for b in bt_t0 if b['pop']<=1], ev_th)
    decompose(f"三連単 tau=0", bs_t0, ev_th)

# キャリブレーション: model_prob vs 的中率 (quintile)
print(f"\n{'='*100}")
print("選択後キャリブレーション (EV>=1.2)")
print(f"{'='*100}")
for label, bets in [("三連複 1fav", [b for b in bt if b['pop']<=1 and b['ev']>=1.2]),
                     ("三連単", [b for b in bs if b['ev']>=1.2])]:
    if len(bets)<50: continue
    probs = np.array([b['model_prob'] for b in bets])
    hits = np.array([b['is_hit'] for b in bets])
    sh_probs = np.array([b['sh_prob'] for b in bets])

    # quintile by model_prob
    q_edges = np.percentile(probs, [0,20,40,60,80,100])
    print(f"\n  {label}: model_prob quintile")
    print(f"  {'Q':>3} {'prob_range':>20} {'n':>7} {'hit':>5} {'pred%':>7} {'actual%':>8} {'ratio':>6}")
    for q in range(5):
        mask = (probs>=q_edges[q]) & (probs<q_edges[q+1]+1e-10)
        if q==4: mask = probs>=q_edges[q]
        n_q=mask.sum(); h_q=hits[mask].sum()
        pred_p=probs[mask].mean()*100 if n_q>0 else 0
        act_p=100*h_q/n_q if n_q>0 else 0
        ratio=act_p/pred_p if pred_p>0 else 0
        print(f"  Q{q+1:>2} {q_edges[q]:.6f}-{q_edges[q+1]:.6f} {n_q:>7,} {h_q:>5,} {pred_p:>6.3f}% {act_p:>7.3f}% {ratio:>5.2f}")

    # sh_prob quintile
    q_edges2 = np.percentile(sh_probs, [0,20,40,60,80,100])
    print(f"\n  {label}: sh_prob quintile")
    print(f"  {'Q':>3} {'prob_range':>20} {'n':>7} {'hit':>5} {'sh%':>7} {'actual%':>8} {'ratio':>6}")
    for q in range(5):
        mask = (sh_probs>=q_edges2[q]) & (sh_probs<q_edges2[q+1]+1e-10)
        if q==4: mask = sh_probs>=q_edges2[q]
        n_q=mask.sum(); h_q=hits[mask].sum()
        sh_p=sh_probs[mask].mean()*100 if n_q>0 else 0
        act_p=100*h_q/n_q if n_q>0 else 0
        ratio=act_p/sh_p if sh_p>0 else 0
        print(f"  Q{q+1:>2} {q_edges2[q]:.6f}-{q_edges2[q+1]:.6f} {n_q:>7,} {h_q:>5,} {sh_p:>6.3f}% {act_p:>7.3f}% {ratio:>5.2f}")

print("\nDone!")
