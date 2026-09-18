# -*- coding: utf-8 -*-
"""v18 シャッフルテスト: ランダム特徴量を追加して3/3 PASSするか確認
全PASSが「+1特徴量による自由度増加」なのか「情報」なのか判定
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
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
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3]})
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]:r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_horses = {}
for rid,_,_,_,_ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?',(rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)
ts3 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=3 AND odds>0').fetchall():
    ts3[rid][hn] = odds
ts5 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=5 AND odds>0').fetchall():
    ts5[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
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

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

js={}; hh={}; ts_st={}; datasets={}; FNAMES=None
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
    if year not in datasets:
        datasets[year]={'X':[],'y':[],'init':[],'meta':[]}
    hl=race_horses.get(rid,[])
    if len(hl)>=5:
        rl=result_cache.get(rid,[])
        if rl:
            winners=[r['hn'] for r in rl if r['fp']==1]
            if winners and winners[0] in hl:
                odds_mkt=ts3.get(rid,{})
                if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
                inv_arr=np.array([1/odds_mkt.get(h,999) for h in hl])
                s=inv_arr.sum()
                if s==0: do_update(); continue
                mp=inv_arr/s; mp=mp**1.015; mp/=mp.sum()
                o5=ts5.get(rid,{}); o3=ts3.get(rid,{})
                has_move=len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
                entries=entry_cache.get(rid,{}); n=len(hl)
                tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
                idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
                riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
                ozd=oz_cache.get(rid,{}); mkt_d=odds_mkt
                oz_inv={h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
                mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
                oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
                cyb_scores=[cyb_cache.get((rid,h),0) for h in hl]
                avg_cyb=np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0
                for i,h in enumerate(hl):
                    ent=entries.get(h,{}); hid=ent.get('hid','')
                    f={}
                    f['idm_c']=(ent.get('idm') or 50)-avg_idm
                    f['rider_c']=(ent.get('rider') or 0)-avg_rider
                    f['total_index']=ent.get('total') or 0
                    oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
                    f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
                    f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
                    jn=ent.get('jockey',''); tn=ent.get('trainer','')
                    jst=js.get(jn,{}); f['jockey_t3rate']=jst.get('t3',0)/jst['r'] if jst.get('r',0)>=30 else -1
                    tst=ts_st.get(tn,{}); f['trainer_t3rate']=tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
                    runs=hh.get(hid,[])
                    f['horse_runs']=len(runs)
                    if runs:
                        rc=runs[-5:]; f['avg_fp_5']=np.mean([r['fp'] for r in rc])
                        f['top3_rate']=sum(1 for r in runs if r['fp']<=3)/len(runs)
                        f['last_fp']=runs[-1]['fp']
                        dr=[r for r in runs if abs(r.get('dist',0)-dt)<=200]
                        f['dist_t3rate']=sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
                        sr=[r for r in runs if r.get('surface')==sf]
                        f['surf_t3rate']=sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
                        f['trend']=runs[-3]['fp']-runs[-1]['fp'] if len(runs)>=3 else 0
                        f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
                    else:
                        f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'dist_t3rate':-1,'surf_t3rate':-1,'trend':0,'win_rate':-1})
                    f['nhead']=n; f['distance']=dt; f['surface']=sf_map.get(sf,0)
                    f['track_cond']=tc_map.get(tc,0); f['grade']=grade_map.get(grade,0)
                    f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
                    f['gate_ratio']=h/n
                    cw=ent.get('weight') or 0
                    avg_cw=np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in hl])
                    f['weight_c']=(cw-avg_cw) if cw>0 else 0
                    if has_move:
                        oo5=o5.get(h,0); oo3=o3.get(h,0)
                        f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
                    else: f['move_5to3']=0
                    if FNAMES is None: FNAMES=sorted(f.keys())
                    datasets[year]['X'].append([f.get(k,0) for k in FNAMES])
                    datasets[year]['y'].append(1 if h==winners[0] else 0)
                    p_val=mp[i]
                    datasets[year]['init'].append(math.log(max(p_val,1e-15))-math.log(max(1-p_val,1e-15)))
                    datasets[year]['meta'].append((rid,h))
    do_update()
for y in sorted(datasets.keys()):
    d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64)
    print(f"  {y}: {len(d['X']):,}")

lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(datasets, fnames):
    results = []
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in datasets]
        fit_yr=test_yr-1
        if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
        X_tr=np.vstack([datasets[y]['X_aug'] for y in train_yrs])
        y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
        dtrain=lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr)
        model=lgb.train(lgb_params,dtrain,num_boost_round=300)
        X_f=datasets[fit_yr]['X_aug']; y_f=datasets[fit_yr]['y']; init_f=datasets[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,hn) in enumerate(datasets[fit_yr]['meta']): rd_f[rid].append(i)
        def neg_ll_base(init, y, rd):
            nll=0; nr=0
            for rid2,idxs in rd.items():
                ys2=y[idxs]; wi=np.where(ys2==1)[0]
                if len(wi)==0: continue
                s=init[idxs]; s=s-s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        def neg_ll(p, init, raw, y, rd):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd.items():
                ys2=y[idxs]; wi=np.where(ys2==1)[0]
                if len(wi)==0: continue
                s=b*init[idxs]+tau*raw[idxs]; s=s-s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res_opt=minimize(lambda p: neg_ll(p, init_f, raw_f, y_f, rd_f),
                         x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        b_use,tau_use=res_opt.x
        X_te=datasets[test_yr]['X_aug']; y_te=datasets[test_yr]['y']
        init_te=datasets[test_yr]['init']
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,hn) in enumerate(datasets[test_yr]['meta']): rd_te[rid].append(i)
        nll_mkt = neg_ll_base(init_te, y_te, rd_te)
        nll_mdl = neg_ll([b_use,tau_use], init_te, raw_te, y_te, rd_te)
        delta = nll_mkt - nll_mdl
        results.append({'year':test_yr,'delta':delta})
    return results

# ベースライン
print("\n=== Baseline ===")
for y in datasets: datasets[y]['X_aug'] = datasets[y]['X']
base_results = run_wf(datasets, FNAMES)
base_deltas = [r['delta'] for r in base_results]
for r in base_results:
    print(f"  {r['year']}: delta={r['delta']:+.5f}")

# シャッフルテスト: 10回ランダム特徴量
print("\n=== Shuffle Test (10 random features) ===")
print(f"  {'seed':>4} {'yr+':>4} {'avg_imp':>10} {'2024':>8} {'2025':>8} {'2026':>8}")
print(f"  {'-'*50}")
pass_count = 0
for seed in range(10):
    np.random.seed(seed + 100)
    for y in datasets:
        n = len(datasets[y]['X'])
        random_feat = np.random.randn(n, 1).astype(np.float32)
        datasets[y]['X_aug'] = np.hstack([datasets[y]['X'], random_feat])
    results = run_wf(datasets, FNAMES + [f'random_{seed}'])
    deltas = [r['delta'] for r in results]
    improvements = [d - bd for d, bd in zip(deltas, base_deltas)]
    yr_plus = sum(1 for imp in improvements if imp > 0)
    avg_imp = np.mean(improvements)
    if yr_plus >= 3: pass_count += 1
    print(f"  {seed:>4} {yr_plus:>3}/3 {avg_imp:>+9.6f} {improvements[0]:>+7.5f} {improvements[1]:>+7.5f} {improvements[2]:>+7.5f}")

print(f"\n  Random 3/3 PASS率: {pass_count}/10 ({pass_count*10}%)")
print(f"  → 候補特徴量の3/3 PASSが意味あるかの判定:")
if pass_count >= 7:
    print(f"  → ランダムでも{pass_count}/10がPASS → 全PASSは自由度増加の産物。特徴量は無価値。")
elif pass_count >= 3:
    print(f"  → ランダムで{pass_count}/10がPASS → 一部の候補は本物かもしれないが、閾値を上げるべき。")
else:
    print(f"  → ランダムで{pass_count}/10しかPASSしない → 候補特徴量の3/3 PASSは本物の可能性あり。")

print("\nDone!")
