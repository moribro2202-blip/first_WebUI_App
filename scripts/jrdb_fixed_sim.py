# -*- coding: utf-8 -*-
"""正規化バグ修正版シミュレーション
修正: softmax後の確率にSH部分和を掛けて絶対確率に戻す
+ τ=0コントロール（モデル残差なしのベースライン）
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
    if es:
        entry_cache[rid] = {e[0]: {'hid': e[1], 'jockey': e[2], 'trainer': e[3], 'idm': e[4], 'total': e[5], 'rider': e[6], 'run_style': e[7], 'weight': e[8]} for e in es}
result_cache = defaultdict(list)
result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn': row[1], 'fp': row[2], 'hid': row[3]})
    result_full[row[0]][row[1]] = row[2]
race_cond = {r[0]: r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]: r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_horses = {}
for rid, _, _, _, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
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
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
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
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
TAKEOUT = {'win':0.20,'umaren':0.225,'sanrenpuku':0.25,'sanrentan':0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def stern_harville_full(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3; S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    umaren=defaultdict(float); trio=defaultdict(float); trifecta={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+=pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                trio[tuple(sorted([i,j,k]))]+=pijk; trifecta[(i,j,k)]=pijk
    return umaren, trio, trifecta

print("Building datasets...", flush=True)
js={}; hh={}; ts_st={}

# 全券種のデータセット
datasets = {}  # {券種: {year: {X,y,init,meta,odds,pop,sh_prob}}}
for bt in ['win','umaren','sanrenpuku','sanrentan']:
    datasets[bt] = {}
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

    umaren_mkt,trio_mkt,trifecta_mkt=stern_harville_full(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
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

    def make_pair(a,b):
        pf={}; f1=feats_h[a]; f2=feats_h[b]
        for k in FEAT_KEYS: pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0); pf[f'{k}_diff']=abs(f1.get(k,0)-f2.get(k,0))
        ow1=f1.get('win_odds_3min',0); ow2=f2.get('win_odds_3min',0)
        pf['win_odds_ratio']=min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
        pf['win_odds_sum_inv']=(1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
        return pf
    def make_trio(a,b,c):
        pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1,v2,v3=f1.get(k,0),f2.get(k,0),f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        ol=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=ol[0]/ol[-1] if len(ol)>=2 and ol[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in ol if o>0)
        return pf

    # 単勝
    ds_w = datasets['win']
    if year not in ds_w: ds_w[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'sh_prob':[]}
    wfn = sorted(FEAT_KEYS)
    if 'win' not in FNAMES: FNAMES['win'] = wfn
    for i,h in enumerate(hl):
        ds_w[year]['X'].append([feats_h[h].get(k,0) for k in wfn])
        ds_w[year]['y'].append(1 if h==winners[0] else 0)
        ds_w[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        ds_w[year]['meta'].append((rid,h)); ds_w[year]['odds'].append(o3.get(h,0))
        ds_w[year]['sh_prob'].append(float(mp[i]))

    # 馬連
    if len(top3_fps)>=2:
        ds_u=datasets['umaren']
        if year not in ds_u: ds_u[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[]}
        wum='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn']]))
        for a,b in combinations(top8,2):
            ai,bi=hl.index(a),hl.index(b); key=tuple(sorted([ai,bi]))
            sh_p=umaren_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b])); pf=make_pair(a,b)
            if 'umaren' not in FNAMES: FNAMES['umaren']=sorted(pf.keys())
            ds_u[year]['X'].append([pf.get(k,0) for k in FNAMES['umaren']])
            ds_u[year]['y'].append(1 if combo==wum else 0)
            ds_u[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            ds_u[year]['meta'].append((rid,combo)); ds_u[year]['odds'].append((1/sh_p)*(1-TAKEOUT['umaren']))
            ds_u[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99)))
            ds_u[year]['sh_prob'].append(float(sh_p))

    # 三連複
    if len(top3_fps)>=3:
        ds_t=datasets['sanrenpuku']
        if year not in ds_t: ds_t[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[]}
        wtr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        for a,b,c in combinations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c])); pf=make_trio(a,b,c)
            if 'sanrenpuku' not in FNAMES: FNAMES['sanrenpuku']=sorted(pf.keys())
            ds_t[year]['X'].append([pf.get(k,0) for k in FNAMES['sanrenpuku']])
            ds_t[year]['y'].append(1 if combo==wtr else 0)
            ds_t[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            ds_t[year]['meta'].append((rid,combo)); ds_t[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrenpuku']))
            ds_t[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            ds_t[year]['sh_prob'].append(float(sh_p))

    # 三連単
    if len(top3_fps)>=3:
        ds_s=datasets['sanrentan']
        if year not in ds_s: ds_s[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[]}
        wst=f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        for a,b,c in permutations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            if top1_idx not in (ai,bi,ci): continue
            sh_p=trifecta_mkt.get((ai,bi,ci),0)
            if sh_p<=0: continue
            combo=f'{a}-{b}-{c}'; pf=make_trio(a,b,c)
            pf['first_prob']=mp[ai]; pf['second_prob']=mp[bi]; pf['third_prob']=mp[ci]
            if 'sanrentan' not in FNAMES: FNAMES['sanrentan']=sorted(pf.keys())
            ds_s[year]['X'].append([pf.get(k,0) for k in FNAMES['sanrentan']])
            ds_s[year]['y'].append(1 if combo==wst else 0)
            ds_s[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            ds_s[year]['meta'].append((rid,combo)); ds_s[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrentan']))
            ds_s[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            ds_s[year]['sh_prob'].append(float(sh_p))
    do_update()

for bt in datasets:
    for y in sorted(datasets[bt].keys()):
        d=datasets[bt][y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        d['sh_prob']=np.array(d['sh_prob'])
        if 'pop' in d: d['pop']=np.array(d['pop'])
    sizes=', '.join(f'{y}:{len(datasets[bt][y]["X"])}' for y in sorted(datasets[bt].keys()))
    print(f"  {bt}: {sizes}")

lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf_fixed(ds, fnames, params, hjc_type, force_tau0=False):
    """修正版WF: softmax後にSH部分和でスケーリング"""
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
            res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
            b_use,tau_use=res.x
        else:
            b_use, tau_use = 1.0, 0.0

        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; odds_te=ds[test_yr]['odds']
        sh_te=ds[test_yr]['sh_prob']
        pop_te=ds[test_yr].get('pop',np.zeros(len(y_te)))
        raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)

        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs_relative=np.exp(s)/np.exp(s).sum()  # sums to 1 over subset

            # === FIX: scale back to absolute probability ===
            sh_subset_sum = sh_te[idxs].sum()
            probs = probs_relative * sh_subset_sum
            # ==============================================

            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; o=odds_te[idx]
                ev=probs[j]*o  # NOW correct: absolute prob × estimated odds
                is_hit=y_te[idx]
                payout=hjc_all.get(rid2,{}).get(hjc_type,{}).get(str(combo) if isinstance(combo,int) else combo,0) if is_hit else 0
                pop_val=int(pop_te[idx]) if len(pop_te)>idx else 0
                all_bets.append({'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'odds':o,'pop':pop_val,'combo':combo})
    return all_bets

def print_results(label, bets, pop_filter=99, odds_lo=0, odds_hi=9999):
    print(f"\n  {label}:")
    print(f"  {'EV>=':>6} {'n':>8} {'hit':>5} {'rec%':>7} | {'2024':>8} {'2025':>8} {'2026':>8}")
    for ev_th in [0.8, 1.0, 1.1, 1.2, 1.3, 1.5]:
        sub=[b for b in bets if b['ev']>=ev_th and b.get('pop',0)<=pop_filter and odds_lo<=b['odds']<=odds_hi]
        if len(sub)<10: continue
        n=len(sub); hits=sum(d['is_hit'] for d in sub)
        inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: parts.append('       -'); continue
            yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f'{yp/yi*100:>7.1f}%')
        print(f"  {ev_th:>5.1f} {n:>8,} {hits:>5,} {rec:>6.1f}% | {' '.join(parts)}")

# === Run ===
print("\nRunning WF (FIXED)...", flush=True)
bw = run_wf_fixed(datasets['win'], FNAMES['win'], lgb_w, 'win_hjc')
bu = run_wf_fixed(datasets['umaren'], FNAMES['umaren'], lgb_p, 'umaren_hjc')
bt = run_wf_fixed(datasets['sanrenpuku'], FNAMES['sanrenpuku'], lgb_p, 'sanrenpuku_hjc')
bs = run_wf_fixed(datasets['sanrentan'], FNAMES['sanrentan'], lgb_p, 'sanrentan_hjc')

# tau=0 control
print("Running tau=0 control...", flush=True)
bt_t0 = run_wf_fixed(datasets['sanrenpuku'], FNAMES['sanrenpuku'], lgb_p, 'sanrenpuku_hjc', force_tau0=True)
bs_t0 = run_wf_fixed(datasets['sanrentan'], FNAMES['sanrentan'], lgb_p, 'sanrentan_hjc', force_tau0=True)

print(f"\n{'='*100}")
print("修正版: softmax正規化バグ修正後")
print(f"{'='*100}")

print_results('単勝 2-40x', bw, odds_lo=2, odds_hi=40)
print_results('馬連 全', bu)
print_results('馬連 1番人気含む', bu, pop_filter=1)
print_results('三連複 全', bt)
print_results('三連複 1番人気含む', bt, pop_filter=1)
print_results('三連単 全', bs)
print_results('三連単 1番人気含む', bs, pop_filter=1)

print(f"\n{'='*100}")
print("tau=0 コントロール（モデル残差なし、SH確率のみ）")
print(f"{'='*100}")
print_results('三連複 1番人気含む (tau=0)', bt_t0, pop_filter=1)
print_results('三連単 1番人気含む (tau=0)', bs_t0, pop_filter=1)

# === EV分布の確認 ===
print(f"\n{'='*100}")
print("EV分布の検証（正規化修正後）")
print(f"{'='*100}")
for label, bets in [('三連複 1fav', [b for b in bt if b['pop']<=1]),
                     ('三連単 1fav', [b for b in bs if b['pop']<=1]),
                     ('三連複 tau0', [b for b in bt_t0 if b['pop']<=1]),
                     ('三連単 tau0', [b for b in bs_t0 if b['pop']<=1])]:
    evs = np.array([b['ev'] for b in bets])
    print(f"  {label}: n={len(evs):,} mean_EV={np.mean(evs):.4f} median={np.median(evs):.4f} "
          f"EV>=1.0: {100*np.mean(evs>=1.0):.1f}% EV>=1.2: {100*np.mean(evs>=1.2):.1f}%")

print("\nDone!")
