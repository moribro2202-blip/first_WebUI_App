# -*- coding: utf-8 -*-
"""三連複トリオ残差モデルの学習・保存
v22アーキテクチャ:
  init_score: SH確率のlogit
  特徴量: トリオレベル（3頭のsum/spread + move_5to3_sum等）
  学習: 2022-2025
  τフィット: 2025年
  保存: data/models/prod_trio_v22.*
"""
import sqlite3, math, sys, os, glob, json, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations
from scipy.optimize import minimize
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB = os.path.join(BASE, 'data', 'jrdb.db')
JRDB = os.path.join(BASE, 'data', 'jrdb')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

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

LAM2, LAM3 = 0.8076, 0.6978
TAKEOUT_TRIO = 0.25
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_trio(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                trio[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    return trio

# データセット構築（2022-2025）
print("Building trio dataset (2022-2025)...", flush=True)
js={}; hh={}; ts_st={}; trio_ds={}; TRFNAMES=None

for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
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
    if year < 2022 or year > 2025: do_update(); continue
    hl = race_horses.get(rid,[])
    if len(hl) < 5: do_update(); continue
    rl = result_cache.get(rid,[])
    if not rl: do_update(); continue
    winners = [r['hn'] for r in rl if r['fp']==1]
    if not winners or winners[0] not in hl: do_update(); continue
    o3 = ts3.get(rid,{}); o5 = ts5.get(rid,{})
    odds_mkt = o3 if len(o3)>=len(hl)*0.8 else sed.get(rid,{})
    has_move = len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
    entries = entry_cache.get(rid,{}); n = len(hl)
    inv_arr = np.array([1/odds_mkt.get(h,999) for h in hl]); s = inv_arr.sum()
    if s == 0: do_update(); continue
    mp = inv_arr/s; mp = mp**1.015; mp /= mp.sum()
    idms = [entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm = np.mean(idms)
    riders = [entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider = np.mean(riders)
    ozd = oz_cache.get(rid,{}); mkt_d = odds_mkt
    oz_inv = {h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
    mk_inv = {h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
    oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1
    cyb_scores = [cyb_cache.get((rid,h),0) for h in hl]
    avg_cyb = np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0
    tc = race_cond.get(rid,'良'); grade = race_grade.get(rid) or '一般'
    fps = result_full.get(rid,{})
    trio_mkt = sh_trio(mp)
    sorted_h = sorted(odds_mkt.items(), key=lambda x:x[1])
    top8 = [h for h,_ in sorted_h[:8]]
    top3_fps = sorted([r for r in rl if r['fp'] in (1,2,3)], key=lambda x:x['fp'])
    if len(top3_fps) < 3: do_update(); continue
    winner_tr = '-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))

    if year not in trio_ds:
        trio_ds[year] = {'X':[],'y':[],'init':[],'meta':[]}

    feats_h = {}
    for i,h in enumerate(hl):
        ent = entries.get(h,{}); hid = ent.get('hid','')
        f = {}
        f['idm_c'] = (ent.get('idm') or 50)-avg_idm
        f['rider_c'] = (ent.get('rider') or 0)-avg_rider
        f['total_index'] = ent.get('total') or 0
        oz_p = oz_inv.get(h,0)/oz_sum; mk_p = mk_inv.get(h,0)/mk_sum
        f['expert_resid'] = math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
        f['cyb_c'] = cyb_cache.get((rid,h),0)-avg_cyb
        jn = ent.get('jockey',''); tn = ent.get('trainer','')
        jst = js.get(jn,{}); f['jockey_t3rate'] = jst.get('t3',0)/jst['r'] if jst.get('r',0)>=30 else -1
        tst = ts_st.get(tn,{}); f['trainer_t3rate'] = tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
        runs = hh.get(hid,[])
        f['horse_runs'] = len(runs)
        if runs:
            rc=runs[-5:]; f['avg_fp_5']=np.mean([r['fp'] for r in rc])
            f['top3_rate']=sum(1 for r in runs if r['fp']<=3)/len(runs)
            f['last_fp']=runs[-1]['fp']
            f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
        else:
            f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
        f['is_senkou'] = 1 if ent.get('run_style','') in ('逃げ','先行') else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        f['win_odds_3min'] = o3.get(h,0)
        feats_h[h] = f

    for a,b,c in combinations(top8,3):
        ai=hl.index(a); bi=hl.index(b); ci=hl.index(c)
        key=tuple(sorted([ai,bi,ci]))
        sh_p=trio_mkt.get(key,0)
        if sh_p<=0: continue
        combo='-'.join(str(x) for x in sorted([a,b,c]))
        pf={}
        f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        odds_list=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in odds_list if o>0)
        if TRFNAMES is None: TRFNAMES=sorted(pf.keys())
        init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
        is_hit=1 if combo==winner_tr else 0
        trio_ds[year]['X'].append([pf.get(k,0) for k in TRFNAMES])
        trio_ds[year]['y'].append(is_hit)
        trio_ds[year]['init'].append(init)
        trio_ds[year]['meta'].append((rid,combo))
    do_update()

for y in sorted(trio_ds.keys()):
    d=trio_ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64)
    n_races=len(set(m[0] for m in d['meta']))
    print(f"  {y}: {len(d['X']):,} trios ({n_races}R)")

# === 学習: 2022-2024 → τフィット: 2025 ===
print("\nTraining trio model (2022-2024)...", flush=True)
lgb_params = {'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
              'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
              'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

train_yrs = [2022, 2023, 2024]
X_tr = np.vstack([trio_ds[y]['X'] for y in train_yrs])
y_tr = np.concatenate([trio_ds[y]['y'] for y in train_yrs])
init_tr = np.concatenate([trio_ds[y]['init'] for y in train_yrs])
n_train = len(X_tr)
print(f"  Training samples: {n_train:,}")

dtrain = lgb.Dataset(X_tr, y_tr, feature_name=TRFNAMES, init_score=init_tr)
model = lgb.train(lgb_params, dtrain, num_boost_round=300)

# τフィット（2025年）
print("Fitting b, tau on 2025...", flush=True)
X_f = trio_ds[2025]['X']; y_f = trio_ds[2025]['y']; init_f = trio_ds[2025]['init']
raw_f = model.predict(X_f, raw_score=True)
rd_f = defaultdict(list)
for i, (rid, combo) in enumerate(trio_ds[2025]['meta']): rd_f[rid].append(i)

def neg_ll(p):
    b, tau = p; nll = 0; nr = 0
    for rid2, idxs in rd_f.items():
        ys = y_f[idxs]; wi = np.where(ys==1)[0]
        if len(wi)==0: continue
        s = b*init_f[idxs]+tau*raw_f[idxs]; s -= s.max()
        nll -= (s[wi[0]]-math.log(np.exp(s).sum())); nr += 1
    return nll/nr if nr > 0 else 999

res = minimize(neg_ll, x0=[1.0, 1.0], method='Nelder-Mead', options={'maxiter':1000})
b_fit, tau_fit = res.x
print(f"  b={b_fit:.4f}, tau={tau_fit:.4f}")

# 特徴量重要度
imp = model.feature_importance(importance_type='gain')
top10 = sorted(zip(TRFNAMES, imp), key=lambda x:-x[1])[:10]
print(f"\n  Top 10 features:")
for name, val in top10:
    print(f"    {name:<25} {val:>8.0f}")

# === 保存 ===
model_file = 'prod_trio_v22.txt'
stats_file = 'prod_trio_stats_v22.json'
config_file = 'prod_trio_config_v22.json'

model.save_model(os.path.join(MODEL_DIR, model_file))

config = {
    'version': 'v22_trio',
    'model_file': model_file,
    'stats_file': stats_file,
    'b': float(b_fit),
    'tau': float(tau_fit),
    'beta': 1.015,
    'lam2': LAM2,
    'lam3': LAM3,
    'takeout': TAKEOUT_TRIO,
    'ev_threshold': 1.2,
    'top_n_horses': 8,
    'feature_names': TRFNAMES,
    'lgb_params': lgb_params,
    'train_years': train_yrs,
    'fit_year': 2025,
    'n_samples': int(n_train),
    'trained_on': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'note': 'Trio residual model. EV judgment uses estimated odds (1/SH_prob * 0.75). Payout uses HJC confirmed. Fable warning: estimated odds give upper bound, need T-3 pool odds for true validation.'
}

with open(os.path.join(MODEL_DIR, config_file), 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

# 統計ファイル（累積統計のスナップショット）
stats = {
    'jockey_stats': {k: v for k, v in js.items() if v['r'] >= 30},
    'trainer_stats': {k: v for k, v in ts_st.items() if v['r'] >= 30},
}
# 馬の成績は大きすぎるので保存しない（リアルタイムで再構築）

with open(os.path.join(MODEL_DIR, stats_file), 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False)

print(f"\n=== Saved ===")
print(f"  Model: {os.path.join(MODEL_DIR, model_file)}")
print(f"  Config: {os.path.join(MODEL_DIR, config_file)}")
print(f"  Stats: {os.path.join(MODEL_DIR, stats_file)}")
print(f"\n  b={b_fit:.4f}, tau={tau_fit:.4f}")
print(f"  EV threshold: 1.2")
print(f"  Top 8 horses, C(8,3)=56 combos per race")
print(f"  Features: {len(TRFNAMES)}")

print("\nDone!")
