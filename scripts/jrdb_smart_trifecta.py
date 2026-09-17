# -*- coding: utf-8 -*-
"""三連複+三連単のうまい所どり検証
三連複モデルで「どの3頭か」、単勝モデルで「誰が1着か」を組み合わせる。

戦略:
  A: 三連複1点(100円) — ベースライン
  B: 三連単ボックス6点(600円) — 全順列
  C: 三連単1着固定2点(200円) — 単勝モデル1位を1着に固定
  D: 三連単1着固定+三連複(300円) — 1着固定2点+三連複1点(保険)
  E: 条件分岐 — 単勝モデルの1位確率が高い時は三連単、低い時は三連複
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')
DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
db = sqlite3.connect(DB, timeout=30)
print("Loading...", flush=True)

races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'trainer':e[3],'idm':e[4],'total':e[5],'rider':e[6],'run_style':e[7],'weight':e[8]} for e in es}
result_cache = defaultdict(list)
result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3]})
    result_full[row[0]][row[1]] = row[2]
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]:r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
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
TAKEOUT_TRIO = 0.25
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_trio(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3; S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2); d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                trio[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    return trio

print("Building...", flush=True)
js={}; hh={}; ts_st={}
tr_ds={}; TRFNAMES=None
win_ds={}; WFNAMES=None

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
    trio_mkt=sh_trio(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1]); rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
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
        wtr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in tr_ds: tr_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[],'horses_in_combo':[]}
        for a,b,c in combinations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c])); pf=make_trio(a,b,c)
            if TRFNAMES is None: TRFNAMES=sorted(pf.keys())
            tr_ds[year]['X'].append([pf.get(k,0) for k in TRFNAMES])
            tr_ds[year]['y'].append(1 if combo==wtr else 0)
            tr_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            tr_ds[year]['meta'].append((rid,combo))
            tr_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT_TRIO))
            tr_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            tr_ds[year]['sh_prob'].append(float(sh_p))
            tr_ds[year]['horses_in_combo'].append((a,b,c))

    # 単勝
    if year not in win_ds: win_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    wfn = sorted(FEAT_KEYS)
    if WFNAMES is None: WFNAMES = wfn
    for i,h in enumerate(hl):
        win_ds[year]['X'].append([feats_h[h].get(k,0) for k in WFNAMES])
        win_ds[year]['y'].append(1 if h==winners[0] else 0)
        win_ds[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        win_ds[year]['meta'].append((rid,h)); win_ds[year]['odds'].append(o3.get(h,0))
    do_update()

for ds in [tr_ds, win_ds]:
    for y in sorted(ds.keys()):
        d=ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        if 'sh_prob' in d: d['sh_prob']=np.array(d['sh_prob'])
        if 'pop' in d: d['pop']=np.array(d['pop'])

lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

# === Run both WFs ===
print("Running trio WF...", flush=True)
trio_bets = []
for test_yr in [2024,2025,2026]:
    ds=tr_ds; fnames=TRFNAMES; params=lgb_p
    train_yrs=[y for y in range(2022,test_yr) if y in ds]; fit_yr=test_yr-1
    if not train_yrs or fit_yr not in ds or test_yr not in ds: continue
    X_tr=np.vstack([ds[y]['X'] for y in train_yrs]); y_tr=np.concatenate([ds[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([ds[y]['init'] for y in train_yrs])
    model=lgb.train(params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
    X_f=ds[fit_yr]['X']; y_f=ds[fit_yr]['y']; init_f=ds[fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True); rd_f=defaultdict(list)
    for i,m in enumerate(ds[fit_yr]['meta']): rd_f[m[0]].append(i)
    def neg_ll(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f.items():
            ys=y_f[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
            nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000}); b_use,tau_use=res.x
    print(f"  trio {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")
    X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
    meta_te=ds[test_yr]['meta']; odds_te=ds[test_yr]['odds']
    sh_te=ds[test_yr]['sh_prob']; pop_te=ds[test_yr]['pop']
    hic_te=ds[test_yr]['horses_in_combo']
    raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
    for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
    for rid2,idxs in rd_te.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
        pr=np.exp(s)/np.exp(s).sum(); sh_sum=sh_te[idxs].sum()
        pa=pr*sh_sum
        for j,idx in enumerate(idxs):
            combo=meta_te[idx][1]; est_o=odds_te[idx]; ev=pa[j]*est_o; is_hit=y_te[idx]
            payout_trio=hjc_all.get(rid2,{}).get('sanrenpuku_hjc',{}).get(combo,0) if is_hit else 0
            horses=hic_te[idx]
            # 三連単の払戻（的中時のみ）
            payout_st=0; actual_order=''
            if is_hit:
                fps=result_full.get(rid2,{})
                top3=sorted([(h,fps.get(h,99)) for h in horses],key=lambda x:x[1])
                actual_order=f'{top3[0][0]}-{top3[1][0]}-{top3[2][0]}'
                payout_st=hjc_all.get(rid2,{}).get('sanrentan_hjc',{}).get(actual_order,0)
            trio_bets.append({
                'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                'payout_trio':payout_trio,'payout_st':payout_st,
                'horses':horses,'combo':combo,'pop':int(pop_te[idx]),
                'actual_order':actual_order,
            })

print("Running win WF...", flush=True)
# 単勝モデルで各レースの馬ごとの勝率を取得
win_probs_by_race = {}  # rid -> {horse_number: model_win_prob}
for test_yr in [2024,2025,2026]:
    ds=win_ds; fnames=WFNAMES; params=lgb_w
    train_yrs=[y for y in range(2022,test_yr) if y in ds]; fit_yr=test_yr-1
    if not train_yrs or fit_yr not in ds or test_yr not in ds: continue
    X_tr=np.vstack([ds[y]['X'] for y in train_yrs]); y_tr=np.concatenate([ds[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([ds[y]['init'] for y in train_yrs])
    model=lgb.train(params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
    X_f=ds[fit_yr]['X']; y_f=ds[fit_yr]['y']; init_f=ds[fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True); rd_f=defaultdict(list)
    for i,m in enumerate(ds[fit_yr]['meta']): rd_f[m[0]].append(i)
    def neg_ll(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f.items():
            ys=y_f[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
            nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000}); b_use,tau_use=res.x
    print(f"  win {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")
    X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
    meta_te=ds[test_yr]['meta']
    raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
    for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
    for rid2,idxs in rd_te.items():
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
        probs=np.exp(s)/np.exp(s).sum()
        wp = {}
        for j,idx in enumerate(idxs):
            hn = meta_te[idx][1]
            wp[hn] = float(probs[j])
        win_probs_by_race[rid2] = wp

# === 分析1: 三連複的中時の1着予測精度 ===
print(f"\n{'='*100}")
print("分析1: 三連複的中時、単勝モデルのtop1が実際に1着だった割合")
print(f"{'='*100}")

trio_hits = [b for b in trio_bets if b['is_hit'] and b['ev']>=1.0 and b['pop']<=1]
print(f"三連複的中数 (EV>=1.0, 1fav): {len(trio_hits)}")

top1_correct = 0
top1_in_trio = 0
for b in trio_hits:
    wp = win_probs_by_race.get(b['rid'], {})
    if not wp: continue
    horses = list(b['horses'])
    # 3頭の中での単勝モデルのtop1
    trio_probs = [(h, wp.get(h, 0)) for h in horses]
    trio_probs.sort(key=lambda x: -x[1])
    predicted_winner = trio_probs[0][0]
    # 実際の1着
    fps = result_full.get(b['rid'], {})
    actual_winner = min(horses, key=lambda h: fps.get(h, 99))
    top1_in_trio += 1
    if predicted_winner == actual_winner:
        top1_correct += 1

pct = 100*top1_correct/top1_in_trio if top1_in_trio>0 else 0
print(f"3頭中のtop1が実際に1着: {top1_correct}/{top1_in_trio} = {pct:.1f}%")
print(f"ランダム期待値: 33.3%")
print(f"リフト: {pct/33.3:.2f}x")
print()

# top2まで含めると
top2_correct = 0
for b in trio_hits:
    wp = win_probs_by_race.get(b['rid'], {})
    if not wp: continue
    horses = list(b['horses'])
    trio_probs = [(h, wp.get(h, 0)) for h in horses]
    trio_probs.sort(key=lambda x: -x[1])
    top2_hn = [trio_probs[0][0], trio_probs[1][0]]
    fps = result_full.get(b['rid'], {})
    actual_winner = min(horses, key=lambda h: fps.get(h, 99))
    if actual_winner in top2_hn:
        top2_correct += 1

pct2 = 100*top2_correct/top1_in_trio if top1_in_trio>0 else 0
print(f"3頭中のtop2に1着が含まれる: {top2_correct}/{top1_in_trio} = {pct2:.1f}%")
print(f"ランダム期待値: 66.7%")

# === 分析2: 全戦略のROI比較 ===
print(f"\n{'='*100}")
print("分析2: 戦略別ROI比較 (EV>=1.0, 1fav, 100円単位)")
print(f"{'='*100}")

for ev_th in [1.0, 1.1, 1.2]:
    cands = [b for b in trio_bets if b['ev']>=ev_th and b['pop']<=1]
    # レース別にEV上位N点
    race_cands = defaultdict(list)
    for b in cands:
        race_cands[b['rid']].append(b)

    for max_pts in [3, 5]:
        print(f"\n  --- EV>={ev_th} max{max_pts}pt 1fav ---")

        strategies = {
            'A:三連複': {'invest':0,'return':0.0,'n_races':0,'yr_invest':defaultdict(int),'yr_return':defaultdict(float)},
            'B:三連単box': {'invest':0,'return':0.0,'n_races':0,'yr_invest':defaultdict(int),'yr_return':defaultdict(float)},
            'C:三連単1着固定': {'invest':0,'return':0.0,'n_races':0,'yr_invest':defaultdict(int),'yr_return':defaultdict(float)},
            'D:1着固定+三連複': {'invest':0,'return':0.0,'n_races':0,'yr_invest':defaultdict(int),'yr_return':defaultdict(float)},
            'E:確率分岐': {'invest':0,'return':0.0,'n_races':0,'yr_invest':defaultdict(int),'yr_return':defaultdict(float)},
        }

        for rid, bets in race_cands.items():
            bets_sorted = sorted(bets, key=lambda x:-x['ev'])[:max_pts]
            yr = bets_sorted[0]['year']
            wp = win_probs_by_race.get(rid, {})

            for b in bets_sorted:
                horses = list(b['horses'])
                is_hit = b['is_hit']
                trio_pay = b['payout_trio']
                st_pay = b['payout_st']

                # 単勝モデルの予測: 3頭中のtop1
                trio_probs = [(h, wp.get(h, 0)) for h in horses]
                trio_probs.sort(key=lambda x: -x[1])
                predicted_1st = trio_probs[0][0]
                predicted_1st_prob = trio_probs[0][1]

                # 実際の着順
                fps = result_full.get(rid, {})
                actual_1st = min(horses, key=lambda h: fps.get(h, 99)) if is_hit else None

                # A: 三連複1点(100円)
                s=strategies['A:三連複']
                s['invest']+=100; s['return']+=trio_pay*100; s['yr_invest'][yr]+=100; s['yr_return'][yr]+=trio_pay*100

                # B: 三連単box6点(600円)
                s=strategies['B:三連単box']
                s['invest']+=600; s['return']+=st_pay*100; s['yr_invest'][yr]+=600; s['yr_return'][yr]+=st_pay*100

                # C: 三連単1着固定2点(200円) — predicted_1stを1着に固定
                s=strategies['C:三連単1着固定']
                s['invest']+=200
                if is_hit and actual_1st == predicted_1st:
                    s['return']+=st_pay*100; s['yr_return'][yr]+=st_pay*100
                s['yr_invest'][yr]+=200

                # D: 1着固定2点+三連複1点(300円)
                s=strategies['D:1着固定+三連複']
                s['invest']+=300; s['yr_invest'][yr]+=300
                ret_d = trio_pay*100  # 三連複は必ず当たる(if is_hit)
                if is_hit and actual_1st == predicted_1st:
                    ret_d += st_pay*100  # 三連単も当たれば追加
                s['return']+=ret_d; s['yr_return'][yr]+=ret_d

                # E: 確率分岐 — predicted_1st_prob >= 0.4 なら三連単1着固定、それ以下なら三連複
                s=strategies['E:確率分岐']
                if predicted_1st_prob >= 0.4:
                    # 三連単1着固定2点
                    s['invest']+=200; s['yr_invest'][yr]+=200
                    if is_hit and actual_1st == predicted_1st:
                        s['return']+=st_pay*100; s['yr_return'][yr]+=st_pay*100
                else:
                    # 三連複1点
                    s['invest']+=100; s['yr_invest'][yr]+=100
                    s['return']+=trio_pay*100; s['yr_return'][yr]+=trio_pay*100

            for sn in strategies:
                strategies[sn]['n_races'] += 1

        print(f"  {'戦略':>20} | {'投資':>10} | {'払戻':>10} | {'利益':>10} | {'ROI':>6} | {'2024':>7} {'2025':>7} {'2026':>7} | {'1R費用':>6}")
        for sn, s in strategies.items():
            if s['invest']==0: continue
            roi=s['return']/s['invest']*100
            profit=s['return']-s['invest']
            n_r=s['n_races']
            avg_cost=s['invest']/n_r if n_r>0 else 0
            yr_parts=[]
            for yr in [2024,2025,2026]:
                if s['yr_invest'][yr]>0:
                    yr_parts.append(f"{s['yr_return'][yr]/s['yr_invest'][yr]*100:>6.1f}%")
                else: yr_parts.append('     -')
            print(f"  {sn:>20} | {s['invest']:>9,}円 | {s['return']:>9,.0f}円 | {profit:>+9,.0f}円 | {roi:>5.1f}% | {' '.join(yr_parts)} | {avg_cost:>5.0f}円")

# === 分析3: 確率閾値の最適化 ===
print(f"\n{'='*100}")
print("分析3: 1着予測確率の閾値別ROI（EV>=1.0 max5 1fav）")
print(f"{'='*100}")

cands = [b for b in trio_bets if b['ev']>=1.0 and b['pop']<=1]
race_cands = defaultdict(list)
for b in cands: race_cands[b['rid']].append(b)

print(f"{'閾値':>6} | {'三連単pts':>9} {'三連複pts':>9} {'total':>6} | {'invest':>10} {'return':>10} {'ROI':>6} | {'hit_1st%':>8}")
for th in [0.0, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60]:
    total_inv=0; total_ret=0.0; st_pts=0; tr_pts=0; n_1st_tries=0; n_1st_ok=0
    for rid, bets in race_cands.items():
        bets_sorted = sorted(bets, key=lambda x:-x['ev'])[:5]
        wp = win_probs_by_race.get(rid, {})
        for b in bets_sorted:
            horses = list(b['horses'])
            trio_probs = [(h, wp.get(h, 0)) for h in horses]
            trio_probs.sort(key=lambda x: -x[1])
            p1 = trio_probs[0][1]
            fps = result_full.get(rid, {})
            actual_1st = min(horses, key=lambda h: fps.get(h, 99)) if b['is_hit'] else None

            if p1 >= th:
                # 三連単1着固定2点
                total_inv += 200; st_pts += 1
                n_1st_tries += 1
                if b['is_hit'] and actual_1st == trio_probs[0][0]:
                    total_ret += b['payout_st']*100
                    n_1st_ok += 1
            else:
                # 三連複1点
                total_inv += 100; tr_pts += 1
                if b['is_hit']:
                    total_ret += b['payout_trio']*100

    roi = total_ret/total_inv*100 if total_inv>0 else 0
    hit_pct = 100*n_1st_ok/n_1st_tries if n_1st_tries>0 else 0
    total = st_pts + tr_pts
    print(f"  {th:>4.2f} | {st_pts:>9,} {tr_pts:>9,} {total:>6,} | {total_inv:>9,}円 {total_ret:>9,.0f}円 {roi:>5.1f}% | {hit_pct:>7.1f}%")

print("\nDone!")
