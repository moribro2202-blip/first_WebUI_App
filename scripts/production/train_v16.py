# -*- coding: utf-8 -*-
"""v16本番モデル学習
Fable最終レビュー対応:
  - 2022年以降のみ学習（偽スナップショット期間を排除）
  - move_5to3（発走3分前判定、送信に2分の余裕）
  - cyb_c対応（CYBファイルから取得）
  - 較正関数（ロジット2次）を含めて保存
  - 統計蓄積は2015年から
"""
import sqlite3, math, sys, os, glob, json, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
from datetime import datetime
import pickle
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

# オッズ: 3分前と5分前
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

# CYB
cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB, 'CYB', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 38: continue
            raw = line.decode('ascii', 'replace')
            rid = f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
            try:
                hn_i = int(raw[8:10])
                score = int(raw[33:35].strip())
            except:
                continue
            cyb_cache[(rid, hn_i)] = score

db.close()
print(f"Loaded. CYB entries: {len(cyb_cache):,}", flush=True)

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

# === データセット構築（統計蓄積は2015年から、学習は2022年以降のみ）===
js = {}; hh = {}; ts_st = {}
datasets = {}; FNAMES = None

for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
    def do_update():
        for res in result_cache.get(rid, []):
            hn, fp, hid = res['hn'], res['fp'], res['hid']
            ent = entry_cache.get(rid, {}).get(hn, {})
            jn = ent.get('jockey', ''); tn = ent.get('trainer', '')
            if jn:
                if jn not in js: js[jn] = {'r': 0, 'w': 0, 't3': 0}
                js[jn]['r'] += 1
                if fp == 1: js[jn]['w'] += 1
                if fp <= 3: js[jn]['t3'] += 1
            if tn:
                if tn not in ts_st: ts_st[tn] = {'r': 0, 'w': 0, 't3': 0}
                ts_st[tn]['r'] += 1
                if fp == 1: ts_st[tn]['w'] += 1
                if fp <= 3: ts_st[tn]['t3'] += 1
            if hid:
                if hid not in hh: hh[hid] = []
                hh[hid].append({'fp': fp, 'dist': dt, 'surface': sf})
                if len(hh[hid]) > 30: hh[hid] = hh[hid][-30:]

    if year < 2022:
        do_update(); continue

    if year not in datasets:
        datasets[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds_3min': []}

    hl = race_horses.get(rid, [])
    if len(hl) >= 5:
        rl = result_cache.get(rid, [])
        if rl:
            winners = [r['hn'] for r in rl if r['fp'] == 1]
            if winners and winners[0] in hl:
                # 市場確率: 3分前オッズ（判定時刻）
                odds_mkt = ts3.get(rid, {})
                if len(odds_mkt) < len(hl) * 0.8:
                    odds_mkt = sed.get(rid, {})
                inv = np.array([1 / odds_mkt.get(h, 999) for h in hl])
                s = inv.sum()
                if s == 0:
                    do_update(); continue
                mp = inv / s; mp = mp ** 1.015; mp /= mp.sum()

                o5 = ts5.get(rid, {}); o3 = ts3.get(rid, {})
                has_move = len(o5) >= len(hl) * 0.8 and len(o3) >= len(hl) * 0.8

                entries = entry_cache.get(rid, {}); n = len(hl)
                tc = race_cond.get(rid, '良'); grade = race_grade.get(rid) or '一般'
                idms = [entries.get(h, {}).get('idm') or 50 for h in hl]; avg_idm = np.mean(idms)
                riders = [entries.get(h, {}).get('rider') or 0 for h in hl]; avg_rider = np.mean(riders)
                oz = oz_cache.get(rid, {}); mkt_d = odds_mkt
                oz_inv = {h: 1 / oz[h] if h in oz and oz[h] > 0 else 0 for h in hl}
                mk_inv = {h: 1 / mkt_d[h] if h in mkt_d and mkt_d[h] > 0 else 0 for h in hl}
                oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1

                # CYBスコア
                cyb_scores = [cyb_cache.get((rid, h), 0) for h in hl]
                avg_cyb = np.mean(cyb_scores) if any(c != 0 for c in cyb_scores) else 0

                for i, h in enumerate(hl):
                    ent = entries.get(h, {}); hid = ent.get('hid', '')
                    idm = ent.get('idm') or 50; rider = ent.get('rider') or 0
                    jn = ent.get('jockey', ''); tn = ent.get('trainer', '')
                    runs = hh.get(hid, [])

                    f = {}
                    f['idm_c'] = idm - avg_idm
                    f['rider_c'] = rider - avg_rider
                    f['total_index'] = ent.get('total') or 0
                    oz_p = oz_inv.get(h, 0) / oz_sum; mk_p = mk_inv.get(h, 0) / mk_sum
                    f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0
                    f['cyb_c'] = cyb_cache.get((rid, h), 0) - avg_cyb

                    jst = js.get(jn, {}); jr = jst.get('r', 0)
                    f['jockey_t3rate'] = jst.get('t3', 0) / jr if jr >= 30 else -1
                    tst = ts_st.get(tn, {}); tr_r = tst.get('r', 0)
                    f['trainer_t3rate'] = tst.get('t3', 0) / tr_r if tr_r >= 30 else -1
                    f['horse_runs'] = len(runs)
                    if runs:
                        rc = runs[-5:]
                        f['avg_fp_5'] = np.mean([r['fp'] for r in rc])
                        f['top3_rate'] = sum(1 for r in runs if r['fp'] <= 3) / len(runs)
                        f['last_fp'] = runs[-1]['fp']
                        dr = [r for r in runs if abs(r.get('dist', 0) - dt) <= 200]
                        f['dist_t3rate'] = sum(1 for r in dr if r['fp'] <= 3) / len(dr) if dr else -1
                        sr = [r for r in runs if r.get('surface') == sf]
                        f['surf_t3rate'] = sum(1 for r in sr if r['fp'] <= 3) / len(sr) if sr else -1
                        f['trend'] = runs[-3]['fp'] - runs[-1]['fp'] if len(runs) >= 3 else 0
                        f['win_rate'] = sum(1 for r in runs if r['fp'] == 1) / len(runs) if len(runs) >= 5 else -1
                    else:
                        f.update({'avg_fp_5': 8, 'top3_rate': 0, 'last_fp': 8, 'dist_t3rate': -1,
                                  'surf_t3rate': -1, 'trend': 0, 'win_rate': -1})

                    f['nhead'] = n; f['distance'] = dt; f['surface'] = sf_map.get(sf, 0)
                    f['track_cond'] = tc_map.get(tc, 0); f['grade'] = grade_map.get(grade, 0)
                    f['is_senkou'] = 1 if ent.get('run_style', '') in ('逃げ', '先行') else 0
                    f['gate_ratio'] = h / n
                    cw = ent.get('weight') or 0
                    avg_cw = np.mean([entries.get(h2, {}).get('weight') or 0 for h2 in hl])
                    f['weight_c'] = (cw - avg_cw) if cw > 0 else 0

                    # move_5to3（発走5分前→3分前の変動）
                    if has_move:
                        oo5 = o5.get(h, 0); oo3 = o3.get(h, 0)
                        f['move_5to3'] = (oo5 - oo3) / oo5 if oo5 > 0 and oo3 > 0 else 0
                    else:
                        f['move_5to3'] = 0

                    if FNAMES is None:
                        FNAMES = sorted(f.keys())
                    datasets[year]['X'].append([f.get(k, 0) for k in FNAMES])
                    datasets[year]['y'].append(1 if h == winners[0] else 0)
                    p = mp[i]
                    datasets[year]['init'].append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))
                    datasets[year]['meta'].append((rid, h))
                    datasets[year]['odds_3min'].append(o3.get(h, 0))
    do_update()

for y in sorted(datasets.keys()):
    d = datasets[y]
    d['X'] = np.array(d['X'], dtype=np.float32); d['y'] = np.array(d['y'])
    d['init'] = np.array(d['init'], dtype=np.float64); d['odds_3min'] = np.array(d['odds_3min'])
    print(f"  {y}: {len(d['X']):,}")

print(f"\n  特徴量({len(FNAMES)}個): {FNAMES}")

# === 学習: 2022-2025全体で学習 ===
print("\n=== 本番モデル学習 ===")
lgb_params = {
    'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
    'num_leaves': 7, 'min_data_in_leaf': 2000, 'feature_fraction': 0.5,
    'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0, 'verbose': -1, 'seed': 42
}

train_years = [y for y in range(2022, 2026) if y in datasets]
X_tr = np.vstack([datasets[y]['X'] for y in train_years])
y_tr = np.concatenate([datasets[y]['y'] for y in train_years])
init_tr = np.concatenate([datasets[y]['init'] for y in train_years])
n_samples = len(X_tr)
print(f"  学習データ: {n_samples:,}サンプル ({train_years})")

dtrain = lgb.Dataset(X_tr, y_tr, feature_name=FNAMES, init_score=init_tr)
model = lgb.train(lgb_params, dtrain, num_boost_round=300)

# === b, τフィット（2025年データで）===
fit_yr = 2025
X_f = datasets[fit_yr]['X']; y_f = datasets[fit_yr]['y']
init_f = datasets[fit_yr]['init']; meta_f = datasets[fit_yr]['meta']
raw_f = model.predict(X_f, raw_score=True)
rd_f = defaultdict(list)
for i, (rid, hn) in enumerate(meta_f):
    rd_f[rid].append(i)

def neg_ll(p):
    b, tau = p; nll = 0; nr = 0
    for rid2, idxs in rd_f.items():
        ys = y_f[idxs]; wi = np.where(ys == 1)[0]
        if len(wi) == 0: continue
        s = b * init_f[idxs] + tau * raw_f[idxs]
        s -= s.max(); nll -= (s[wi[0]] - math.log(np.exp(s).sum())); nr += 1
    return nll / nr if nr > 0 else 999

res = minimize(neg_ll, x0=[1.0, 1.0], method='Nelder-Mead', options={'maxiter': 1000})
b_fit, tau_fit = res.x
print(f"  b={b_fit:.4f}, τ={tau_fit:.4f}")

# === 較正関数フィット（2025年） ===
cal_probs = []; cal_labels = []
for rid2, idxs in rd_f.items():
    ys = y_f[idxs]; wi = np.where(ys == 1)[0]
    if len(wi) == 0: continue
    s = b_fit * init_f[idxs] + tau_fit * raw_f[idxs]
    s -= s.max(); tp = np.exp(s) / np.exp(s).sum()
    for j, idx in enumerate(idxs):
        cal_probs.append(tp[j]); cal_labels.append(y_f[idx])

cal_probs = np.array(cal_probs); cal_labels = np.array(cal_labels)
logit_p = np.log(np.clip(cal_probs, 1e-8, 1 - 1e-8) / (1 - np.clip(cal_probs, 1e-8, 1 - 1e-8)))
X_cal = np.column_stack([logit_p, logit_p ** 2])
cal_model = LogisticRegression(C=1e6, max_iter=1000).fit(X_cal, cal_labels)
cal_intercept = float(cal_model.intercept_[0])
cal_coef1 = float(cal_model.coef_[0][0])
cal_coef2 = float(cal_model.coef_[0][1])
print(f"  較正: intercept={cal_intercept:.4f} coef1={cal_coef1:.4f} coef2={cal_coef2:.4f}")

# === 統計情報保存 ===
stats = {
    'jockey_stats': {k: v for k, v in js.items() if v['r'] >= 30},
    'trainer_stats': {k: v for k, v in ts_st.items() if v['r'] >= 30},
    'horse_history': {k: v for k, v in hh.items() if len(v) >= 1},
}

# === 保存 ===
model_file = 'prod_model_v16.txt'
stats_file = 'prod_stats_v16.json'
model.save_model(os.path.join(MODEL_DIR, model_file))

with open(os.path.join(MODEL_DIR, stats_file), 'w', encoding='utf-8') as f:
    json.dump(stats, f, ensure_ascii=False)

config = {
    'feature_names': FNAMES,
    'b': b_fit,
    'tau': tau_fit,
    'beta': 1.015,
    'ev_threshold': 1.20,
    'model_file': model_file,
    'stats_file': stats_file,
    'lgb_params': lgb_params,
    'calibration': {
        'intercept': cal_intercept,
        'coef1': cal_coef1,
        'coef2': cal_coef2,
        'fit_year': fit_yr,
        'formula': 'logit(p_cal) = intercept + coef1*logit(p) + coef2*logit(p)^2',
    },
    'trained_on': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'n_samples': n_samples,
    'train_years': train_years,
    'move_feature': 'move_5to3',
    'judgment_time': '発走3分前',
    'version': 'v16',
}

with open(os.path.join(MODEL_DIR, 'prod_config.json'), 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"\n  保存完了:")
print(f"    モデル: {model_file}")
print(f"    統計: {stats_file}")
print(f"    設定: prod_config.json")

# === feature importance ===
imp = model.feature_importance(importance_type='gain')
top = sorted(zip(FNAMES, imp), key=lambda x: -x[1])
print(f"\n  特徴量重要度 (top10):")
for name, gain in top[:10]:
    print(f"    {name:>20}: {gain:>8.0f}")

print(f"\nDone!")
