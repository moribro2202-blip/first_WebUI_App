# -*- coding: utf-8 -*-
"""本番用モデルの学習・保存
全過去データで学習し、モデルとτパラメータを保存する。

出力:
  data/models/prod_model.txt  - LightGBMモデル
  data/models/prod_config.json - τ, b, 特徴量名, パラメータ
"""
import sqlite3, math, sys, os, glob, json, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB = os.path.join(BASE, 'data', 'jrdb.db')
JRDB = os.path.join(BASE, 'data', 'jrdb')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

db = sqlite3.connect(DB)
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
ts1 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds
ts5 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=5 AND odds>0').fetchall():
    ts5[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
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
oz_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
db.close()
print("Data loaded.", flush=True)

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

def get_market_p(rid, hl):
    odds_src = ts1.get(rid, {})
    if len(odds_src) < len(hl)*0.8: odds_src = sed.get(rid, {})
    inv = np.array([1/odds_src.get(h,999) for h in hl])
    s = inv.sum()
    if s == 0: return None
    p = inv/s; p = p**1.015; p /= p.sum()
    return p

def update_stats(rid, rd, vc, sf, dt, js, hh, ts_st):
    for res in result_cache.get(rid, []):
        hn, fp, hid = res['hn'], res['fp'], res['hid']
        ent = entry_cache.get(rid, {}).get(hn, {})
        jn = ent.get('jockey',''); tn = ent.get('trainer','')
        if jn:
            if jn not in js: js[jn]={'r':0,'t3':0}
            js[jn]['r']+=1; js[jn]['t3']+=(fp<=3)
        if tn:
            if tn not in ts_st: ts_st[tn]={'r':0,'t3':0}
            ts_st[tn]['r']+=1; ts_st[tn]['t3']+=(fp<=3)
        if hid:
            if hid not in hh: hh[hid]=[]
            hh[hid].append({'fp':fp,'dist':dt,'surface':sf})
            if len(hh[hid])>30: hh[hid]=hh[hid][-30:]

# === Build training data (ALL years) ===
print("Building training data...", flush=True)
js={}; hh={}; ts_st={}
FNAMES=None; X_all=[]; y_all=[]; init_all=[]; meta_all=[]

for rid,rd,vc,sf,dt in races_raw:
    hl=race_horses.get(rid,[])
    if len(hl)>=5:
        rl=result_cache.get(rid,[])
        if rl:
            winners=[r['hn'] for r in rl if r['fp']==1]
            if winners and winners[0] in hl:
                mp=get_market_p(rid,hl)
                if mp is not None:
                    entries=entry_cache.get(rid,{})
                    n=len(hl); tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
                    idms=[entries.get(h,{}).get('idm') or 50 for h in hl]
                    avg_idm=np.mean(idms)
                    riders=[entries.get(h,{}).get('rider') or 0 for h in hl]
                    avg_rider=np.mean(riders)
                    oz=oz_cache.get(rid,{}); mkt=ts1.get(rid,sed.get(rid,{}))
                    oz_inv={h:1/oz[h] if h in oz and oz[h]>0 else 0 for h in hl}
                    mk_inv={h:1/mkt[h] if h in mkt and mkt[h]>0 else 0 for h in hl}
                    oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
                    cybs=[cyb_cache.get((rid,h),0) for h in hl]; avg_cyb=np.mean(cybs) if cybs else 50
                    o5d=ts5.get(rid,{}); o1d=ts1.get(rid,{})
                    has_ts=len(o5d)>=n*0.8
                    for i,h in enumerate(hl):
                        ent=entries.get(h,{}); hid=ent.get('hid','')
                        idm=ent.get('idm') or 50; rider=ent.get('rider') or 0
                        jn=ent.get('jockey',''); tn=ent.get('trainer','')
                        runs=hh.get(hid,[])
                        f={}
                        f['idm_c']=idm-avg_idm; f['rider_c']=rider-avg_rider
                        f['total_index']=ent.get('total') or 0
                        oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
                        f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
                        f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
                        jst=js.get(jn,{}); jr=jst.get('r',0)
                        f['jockey_t3rate']=jst.get('t3',0)/jr if jr>=30 else -1
                        tst=ts_st.get(tn,{}); tr=tst.get('r',0)
                        f['trainer_t3rate']=tst.get('t3',0)/tr if tr>=30 else -1
                        f['horse_runs']=len(runs)
                        if runs:
                            rc=runs[-5:]
                            f['avg_fp_5']=np.mean([r['fp'] for r in rc])
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
                        cw=ent.get('weight') or 0; avg_cw=np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in hl])
                        f['weight_c']=(cw-avg_cw) if cw>0 else 0
                        if has_ts:
                            oo5=o5d.get(h,0); oo1=o1d.get(h,0)
                            f['move_5to1']=(oo5-oo1)/oo5 if oo5>0 and oo1>0 else 0
                        else: f['move_5to1']=0
                        if FNAMES is None: FNAMES=sorted(f.keys())
                        X_all.append([f.get(k,0) for k in FNAMES])
                        y_all.append(1 if h==winners[0] else 0)
                        p=mp[i]
                        init_all.append(math.log(max(p,1e-15))-math.log(max(1-p,1e-15)))
                        meta_all.append((rid,h))
    update_stats(rid,rd,vc,sf,dt,js,hh,ts_st)

X_all=np.array(X_all,dtype=np.float32); y_all=np.array(y_all)
init_all=np.array(init_all,dtype=np.float64)

# Winsorize
for cn in ['expert_resid','move_5to1','cyb_c']:
    ci=FNAMES.index(cn); col=X_all[:,ci]; mu=col.mean(); sd=col.std()
    if sd>0: X_all[:,ci]=np.clip(col,mu-3*sd,mu+3*sd)

print(f"  Training data: {len(X_all):,} samples, {y_all.sum():,} wins")
print(f"  Features: {len(FNAMES)}")

# === Train LightGBM ===
print("\nTraining LightGBM...", flush=True)
params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
        'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
        'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

dtrain=lgb.Dataset(X_all,y_all,feature_name=FNAMES,init_score=init_all)
model=lgb.train(params,dtrain,num_boost_round=300)

# === Fit τ on last 2 years ===
print("Fitting τ on last 2 years...", flush=True)
# Get races from last 2 years
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')

fit_indices = []
race_groups = defaultdict(list)
for i, (rid, hn) in enumerate(meta_all):
    rd = None
    for r in races_raw:
        if r[0] == rid:
            rd = r[1]; break
    if rd and rd >= cutoff:
        race_groups[rid].append(i)

raw_all = model.predict(X_all, raw_score=True)

def neg_ll(params):
    b, tau = params
    nll=0; n=0
    for rid, idxs in race_groups.items():
        idxs = np.array(idxs)
        s = b*init_all[idxs] + tau*raw_all[idxs]
        s -= s.max(); exp_s=np.exp(s)
        y_race = y_all[idxs]
        wi=np.where(y_race==1)[0]
        if len(wi)==0: continue
        nll -= (s[wi[0]] - math.log(exp_s.sum()))
        n += 1
    return nll/n if n>0 else 999

res = minimize(neg_ll, x0=[1.0,1.0], method='Nelder-Mead', options={'maxiter':1000})
b_opt, tau_opt = res.x
print(f"  b={b_opt:.4f}, τ={tau_opt:.4f}")

# === Save ===
model_path = os.path.join(MODEL_DIR, 'prod_model.txt')
model.save_model(model_path)

# Save walk-forward stats for runtime feature computation
stats_path = os.path.join(MODEL_DIR, 'prod_stats.json')
stats = {
    'jockey_stats': {jn: {'r':v['r'],'t3':v['t3']} for jn,v in js.items() if v['r']>=30},
    'trainer_stats': {tn: {'r':v['r'],'t3':v['t3']} for tn,v in ts_st.items() if v['r']>=30},
    'horse_history': {hid: runs[-10:] for hid,runs in hh.items() if runs},
}
with open(stats_path, 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False)

config = {
    'feature_names': FNAMES,
    'b': float(b_opt),
    'tau': float(tau_opt),
    'beta': 1.015,
    'ev_threshold': 1.10,
    'model_file': 'prod_model.txt',
    'stats_file': 'prod_stats.json',
    'lgb_params': params,
    'trained_on': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'n_samples': len(X_all),
    'tau_fit_period': '2 years',
    'tau_fit_cutoff': cutoff,
}
config_path = os.path.join(MODEL_DIR, 'prod_config.json')
with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"\n=== Saved ===")
print(f"  Model: {model_path}")
print(f"  Stats: {stats_path}")
print(f"  Config: {config_path}")
print(f"  b={b_opt:.4f}, τ={tau_opt:.4f}")
print(f"  EV threshold: 1.0")

# Feature importance
imp = model.feature_importance(importance_type='gain')
fi = sorted(zip(FNAMES, imp), key=lambda x: -x[1])
print(f"\n  Top features:")
for name, val in fi[:10]:
    print(f"    {name:<22} {val:>10.1f}")

print(f"\nDone!")
