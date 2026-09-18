# -*- coding: utf-8 -*-
"""モデル予測的中率 vs 実際の勝率・複勝率（オッズ帯別・予測確率帯別）"""
import sqlite3, math, sys, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB)
print("Loading...", flush=True)

races_raw = db.execute(
    "SELECT race_id,race_date,venue_code,surface,distance FROM races "
    "WHERE race_date >= '2022-01-01' ORDER BY race_date,race_id"
).fetchall()

entry_cache = {}
for rid, _, _, _, _ in races_raw:
    es = db.execute(
        'SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,'
        'rider_index,run_style,carried_weight FROM entries WHERE race_id=?', (rid,)
    ).fetchall()
    if es:
        entry_cache[rid] = {e[0]: {'hid': e[1], 'jockey': e[2], 'trainer': e[3],
            'idm': e[4], 'total': e[5], 'rider': e[6], 'run_style': e[7], 'weight': e[8]} for e in es}

result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_full[row[0]][row[1]] = row[2]

race_horses = {}
for rid, _, _, _, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs:
        race_horses[rid] = sorted(hs)

ts1 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds
ts5 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=5 AND odds>0').fetchall():
    ts5[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall()
    if oz:
        oz_cache[rid] = {int(r[0]): r[1] for r in oz}

race_cond = {r[0]: r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]: r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
db.close()
print("Loaded.", flush=True)

grade_map = {'G1': 6, 'G2': 5, 'G3': 4, 'OP': 3, 'L': 2, '3勝': 1, '2勝': 0, '1勝': -1,
             '未勝利': -2, '新馬': -3, '一般': 0}
tc_map = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
sf_map = {'芝': 0, 'ダート': 1}

js = {}; hh = {}; ts_st = {}
datasets = {}; FNAMES = None

for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
    def do_update():
        for hn, fp in result_full.get(rid, {}).items():
            ent = entry_cache.get(rid, {}).get(hn, {})
            jn = ent.get('jockey', ''); tn = ent.get('trainer', ''); hid = ent.get('hid', '')
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

    if year not in datasets:
        datasets[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds_1min': []}
    hl = race_horses.get(rid, [])
    if len(hl) >= 5:
        fps = result_full.get(rid, {})
        winners = [hn for hn, fp in fps.items() if fp == 1]
        if winners and winners[0] in hl:
            odds_mkt = ts1.get(rid, {})
            if len(odds_mkt) < len(hl) * 0.8:
                odds_mkt = sed.get(rid, {})
            inv = np.array([1 / odds_mkt.get(h, 999) for h in hl])
            s = inv.sum()
            if s == 0:
                do_update(); continue
            mp = inv / s; mp = mp ** 1.015; mp /= mp.sum()
            o5 = ts5.get(rid, {}); o1 = ts1.get(rid, {})
            has_move = len(o5) >= len(hl) * 0.8 and len(o1) >= len(hl) * 0.8
            entries = entry_cache.get(rid, {}); n = len(hl)
            tc = race_cond.get(rid, '良'); grade = race_grade.get(rid) or '一般'
            idms = [entries.get(h, {}).get('idm') or 50 for h in hl]; avg_idm = np.mean(idms)
            riders = [entries.get(h, {}).get('rider') or 0 for h in hl]; avg_rider = np.mean(riders)
            oz = oz_cache.get(rid, {}); mkt_d = odds_mkt
            oz_inv = {h: 1 / oz[h] if h in oz and oz[h] > 0 else 0 for h in hl}
            mk_inv = {h: 1 / mkt_d[h] if h in mkt_d and mkt_d[h] > 0 else 0 for h in hl}
            oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1
            for i, h in enumerate(hl):
                ent = entries.get(h, {}); hid = ent.get('hid', '')
                idm = ent.get('idm') or 50; rider = ent.get('rider') or 0
                jn = ent.get('jockey', ''); tn = ent.get('trainer', '')
                runs = hh.get(hid, [])
                f = {}
                f['idm_c'] = idm - avg_idm; f['rider_c'] = rider - avg_rider
                f['total_index'] = ent.get('total') or 0
                oz_p = oz_inv.get(h, 0) / oz_sum; mk_p = mk_inv.get(h, 0) / mk_sum
                f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0
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
                if has_move:
                    oo5 = o5.get(h, 0); oo1 = o1.get(h, 0)
                    f['move_5to1'] = (oo5 - oo1) / oo5 if oo5 > 0 and oo1 > 0 else 0
                else:
                    f['move_5to1'] = 0
                if FNAMES is None:
                    FNAMES = sorted(f.keys())
                datasets[year]['X'].append([f.get(k, 0) for k in FNAMES])
                datasets[year]['y'].append(1 if h == winners[0] else 0)
                p = mp[i]
                datasets[year]['init'].append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))
                datasets[year]['meta'].append((rid, h))
                datasets[year]['odds_1min'].append(o1.get(h, 0))
    do_update()

for y in sorted(datasets.keys()):
    d = datasets[y]
    d['X'] = np.array(d['X'], dtype=np.float32); d['y'] = np.array(d['y'])
    d['init'] = np.array(d['init'], dtype=np.float64); d['odds_1min'] = np.array(d['odds_1min'])
    print(f"  {y}: {len(d['X']):,}")

params = {'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
          'num_leaves': 7, 'min_data_in_leaf': 2000, 'feature_fraction': 0.5,
          'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0, 'verbose': -1, 'seed': 42}

# WF
all_data = []
for test_yr in [2024, 2025, 2026]:
    train_yrs = [y for y in range(2022, test_yr) if y in datasets]
    fit_yr = test_yr - 1
    if not train_yrs or fit_yr not in datasets or test_yr not in datasets:
        continue
    X_tr = np.vstack([datasets[y]['X'] for y in train_yrs])
    y_tr = np.concatenate([datasets[y]['y'] for y in train_yrs])
    init_tr = np.concatenate([datasets[y]['init'] for y in train_yrs])
    dtrain = lgb.Dataset(X_tr, y_tr, feature_name=FNAMES, init_score=init_tr)
    model = lgb.train(params, dtrain, num_boost_round=300)

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
            s -= s.max()
            nll -= (s[wi[0]] - math.log(np.exp(s).sum()))
            nr += 1
        return nll / nr if nr > 0 else 999

    res = minimize(neg_ll, x0=[1.0, 1.0], method='Nelder-Mead', options={'maxiter': 1000})
    b_use, tau_use = res.x

    X_te = datasets[test_yr]['X']; y_te = datasets[test_yr]['y']
    init_te = datasets[test_yr]['init']; meta_te = datasets[test_yr]['meta']
    odds_te = datasets[test_yr]['odds_1min']
    raw_te = model.predict(X_te, raw_score=True)
    race_data = defaultdict(list)
    for i, (rid, hn) in enumerate(meta_te):
        race_data[rid].append(i)

    for rid2, idxs in race_data.items():
        ys = y_te[idxs]; wi = np.where(ys == 1)[0]
        if len(wi) == 0: continue
        s = b_use * init_te[idxs] + tau_use * raw_te[idxs]
        s -= s.max()
        tau_p = np.exp(s) / np.exp(s).sum()
        hns = [meta_te[i][1] for i in idxs]
        fps = result_full.get(rid2, {})
        for j, idx in enumerate(idxs):
            o = odds_te[idx]
            fp = fps.get(hns[j], 99)
            all_data.append({
                'odds': o, 'model_p': float(tau_p[j]),
                'fp': fp, 'is_win': int(fp == 1),
                'is_place': int(fp <= 3), 'is_top2': int(fp <= 2),
            })

print(f"\nTotal: {len(all_data):,}")

# === 分析1: 市場オッズ帯別 ===
print(f"\n{'='*95}")
print("モデル予測的中率 vs 実際の勝率・複勝率（市場オッズ帯別、全馬、2024-2026）")
print(f"{'='*95}")
print(f"  {'オッズ帯':>10} {'n':>7} | {'予測勝率':>8} {'実勝率':>7} {'比':>5} | {'実複勝率':>8} {'複/勝':>6} | {'実連対率':>8}")
print(f"  {'-'*80}")

bands = [(1, 2), (2, 3), (3, 5), (5, 8), (8, 12), (12, 20), (20, 35), (35, 60), (60, 100), (100, 500)]
for lo, hi in bands:
    sub = [d for d in all_data if lo <= d['odds'] < hi]
    if not sub: continue
    n = len(sub)
    pred_win = np.mean([d['model_p'] for d in sub])
    act_win = np.mean([d['is_win'] for d in sub])
    act_place = np.mean([d['is_place'] for d in sub])
    act_top2 = np.mean([d['is_top2'] for d in sub])
    ratio = act_win / pred_win if pred_win > 0 else 0
    place_ratio = act_place / act_win if act_win > 0 else 0
    print(f"  {lo:>3}-{hi:<4}x {n:>7} | {pred_win:>7.4f} {act_win:>6.4f} {ratio:>4.2f} | {act_place:>7.4f} {place_ratio:>5.2f}x | {act_top2:>7.4f}")

# === 分析2: モデル予測確率帯別 ===
print(f"\n{'='*95}")
print("モデル予測確率帯別: 予測勝率 vs 実勝率 vs 実複勝率")
print(f"{'='*95}")
print(f"  {'予測P帯':>14} {'n':>7} | {'予測勝率':>8} {'実勝率':>7} {'勝比':>5} | {'実複勝率':>8} {'複/勝':>6} | {'avgOdds':>8}")
print(f"  {'-'*85}")

p_bands = [(0, 0.01), (0.01, 0.02), (0.02, 0.04), (0.04, 0.07), (0.07, 0.10),
           (0.10, 0.15), (0.15, 0.25), (0.25, 0.40), (0.40, 1.0)]
for lo, hi in p_bands:
    sub = [d for d in all_data if lo <= d['model_p'] < hi]
    if not sub: continue
    n = len(sub)
    pred = np.mean([d['model_p'] for d in sub])
    act_w = np.mean([d['is_win'] for d in sub])
    act_p = np.mean([d['is_place'] for d in sub])
    ratio_w = act_w / pred if pred > 0 else 0
    place_ratio = act_p / act_w if act_w > 0 else 0
    avg_odds = np.mean([d['odds'] for d in sub])
    print(f"  {lo:.2f}-{hi:.2f} {n:>7} | {pred:>7.4f} {act_w:>6.4f} {ratio_w:>4.2f} | {act_p:>7.4f} {place_ratio:>5.2f}x | {avg_odds:>7.1f}")

# === 分析3: 複勝率/勝率の比率 ===
print(f"\n{'='*95}")
print("複勝率/勝率の比率（Harvilleの妥当性検証）")
print(f"{'='*95}")
print("理論: Harville均等場では複勝率 ≈ 3×勝率。実際はオッズ帯で異なる")
print(f"  {'オッズ帯':>10} {'実勝率':>7} {'実複勝率':>8} {'複勝/勝率':>9}")
print(f"  {'-'*40}")
for lo, hi in bands:
    sub = [d for d in all_data if lo <= d['odds'] < hi]
    if not sub: continue
    act_w = np.mean([d['is_win'] for d in sub])
    act_p = np.mean([d['is_place'] for d in sub])
    ratio = act_p / act_w if act_w > 0 else 0
    print(f"  {lo:>3}-{hi:<4}x {act_w:>6.4f} {act_p:>7.4f} {ratio:>8.2f}x")

print("\nDone!")
