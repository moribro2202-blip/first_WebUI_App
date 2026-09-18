# -*- coding: utf-8 -*-
"""経路B: 実運用可能な特徴量だけで正直なバックテスト
- move_5to1を除外（実運用で取得不可）
- b=1.0固定（市場確率を圧縮しない）
- オッズ帯別キャリブレーション検証
- Δ_τ・EVラダー・年別を全部再計測
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
db = sqlite3.connect(DB)
print("Loading data...", flush=True)

# === データロード（phase4_tau_laggedと同じ） ===
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid, _, _, _, _ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?', (rid,)).fetchall()
    if es:
        entry_cache[rid] = {e[0]: {'hid': e[1], 'jockey': e[2], 'trainer': e[3], 'idm': e[4], 'total': e[5], 'rider': e[6], 'run_style': e[7], 'weight': e[8]} for e in es}

result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn': row[1], 'fp': row[2], 'hid': row[3]})

race_cond = {r[0]: r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]: r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_horses = {}
for rid, _, _, _, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs:
        race_horses[rid] = sorted(hs)

# 1分前オッズ
ts1 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds
# 確定オッズ
ts0 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=0 AND odds>0').fetchall():
    ts0[rid][hn] = odds
# SED確定オッズ
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
# 前日オッズ
oz_cache = {}
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall()
    if oz:
        oz_cache[rid] = {int(r[0]): r[1] for r in oz}
# HJC確定オッズ
hjc_cache = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try:
        hjc_cache[row[0]][int(row[1])] = row[2]
    except:
        pass

db.close()
print("Data loaded.", flush=True)

grade_map = {'G1': 6, 'G2': 5, 'G3': 4, 'OP': 3, 'L': 2, '3勝': 1, '2勝': 0, '1勝': -1, '未勝利': -2, '新馬': -3, '一般': 0}
tc_map = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
sf_map = {'芝': 0, 'ダート': 1}


def get_market_p_1min(rid, hl):
    odds_src = ts1.get(rid, {})
    if len(odds_src) < len(hl) * 0.8:
        odds_src = sed.get(rid, {})
    inv = np.array([1 / odds_src.get(h, 999) for h in hl])
    s = inv.sum()
    if s == 0:
        return None
    p = inv / s
    p = p ** 1.015
    p /= p.sum()
    return p


# === 統計更新 ===
def update_stats(rid, rd, vc, sf, dt, js, hh, ts_st):
    for res in result_cache.get(rid, []):
        hn, fp, hid = res['hn'], res['fp'], res['hid']
        ent = entry_cache.get(rid, {}).get(hn, {})
        jn = ent.get('jockey', '')
        tn = ent.get('trainer', '')
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
            hh[hid].append({'fp': fp, 'dist': dt, 'surface': sf, 'cond': race_cond.get(rid, '良')})
            if len(hh[hid]) > 30: hh[hid] = hh[hid][-30:]


# === 特徴量構築（move_5to1を除外） ===
def build_features(rid, hl, js, hh, ts_st, rd, vc, sf, dt):
    entries = entry_cache.get(rid, {})
    n = len(hl)
    tc = race_cond.get(rid, '良')
    grade = race_grade.get(rid) or '一般'
    idms = [entries.get(h, {}).get('idm') or 50 for h in hl]
    avg_idm = np.mean(idms)
    riders = [entries.get(h, {}).get('rider') or 0 for h in hl]
    avg_rider = np.mean(riders)
    oz = oz_cache.get(rid, {})
    mkt = ts1.get(rid, sed.get(rid, {}))
    oz_inv = {h: 1 / oz[h] if h in oz and oz[h] > 0 else 0 for h in hl}
    mk_inv = {h: 1 / mkt[h] if h in mkt and mkt[h] > 0 else 0 for h in hl}
    oz_sum = sum(oz_inv.values()) or 1
    mk_sum = sum(mk_inv.values()) or 1

    rows = []
    for h in hl:
        ent = entries.get(h, {})
        hid = ent.get('hid', '')
        idm = ent.get('idm') or 50
        rider = ent.get('rider') or 0
        jn = ent.get('jockey', '')
        tn = ent.get('trainer', '')

        f = {}
        f['idm_c'] = idm - avg_idm
        f['rider_c'] = rider - avg_rider
        f['total_index'] = ent.get('total') or 0
        oz_p = oz_inv.get(h, 0) / oz_sum
        mk_p = mk_inv.get(h, 0) / mk_sum
        f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0

        jst = js.get(jn, {})
        jr = jst.get('r', 0)
        f['jockey_t3rate'] = jst.get('t3', 0) / jr if jr >= 30 else -1
        tst = ts_st.get(tn, {})
        tr_r = tst.get('r', 0)
        f['trainer_t3rate'] = tst.get('t3', 0) / tr_r if tr_r >= 30 else -1

        runs = hh.get(hid, [])
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

        f['nhead'] = n
        f['distance'] = dt
        f['surface'] = sf_map.get(sf, 0)
        f['track_cond'] = tc_map.get(tc, 0)
        f['grade'] = grade_map.get(grade, 0)
        f['is_senkou'] = 1 if ent.get('run_style', '') in ('逃げ', '先行') else 0
        f['gate_ratio'] = h / n
        cw = ent.get('weight') or 0
        avg_cw = np.mean([entries.get(h2, {}).get('weight') or 0 for h2 in hl])
        f['weight_c'] = (cw - avg_cw) if cw > 0 else 0
        # move_5to1 は除外（実運用で取得不可）
        rows.append((h, f))
    return rows


# === データセット構築 ===
print("\nBuilding datasets (without move_5to1)...", flush=True)
js = {}; hh = {}; ts_st = {}
FNAMES = None
datasets = {}

for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
    if year < 2015:
        update_stats(rid, rd, vc, sf, dt, js, hh, ts_st)
        continue
    if year not in datasets:
        datasets[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds_1min': [], 'odds_conf': []}
    hl = race_horses.get(rid, [])
    if len(hl) >= 5:
        rl = result_cache.get(rid, [])
        if rl:
            winners = [r['hn'] for r in rl if r['fp'] == 1]
            if winners and winners[0] in hl:
                mp = get_market_p_1min(rid, hl)
                if mp is not None:
                    feats = build_features(rid, hl, js, hh, ts_st, rd, vc, sf, dt)
                    if feats:
                        if FNAMES is None:
                            FNAMES = sorted(feats[0][1].keys())
                        for i, (hn, f) in enumerate(feats):
                            datasets[year]['X'].append([f.get(k, 0) for k in FNAMES])
                            datasets[year]['y'].append(1 if hn == winners[0] else 0)
                            p = mp[i]
                            datasets[year]['init'].append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))
                            datasets[year]['meta'].append((rid, hn))
                            datasets[year]['odds_1min'].append(ts1.get(rid, {}).get(hn, 0))
                            datasets[year]['odds_conf'].append(ts0.get(rid, {}).get(hn, 0))
    update_stats(rid, rd, vc, sf, dt, js, hh, ts_st)

del js, hh, ts_st

# Winsorize
winsorize_cols = ['expert_resid']
for y in sorted(datasets.keys()):
    d = datasets[y]
    d['X'] = np.array(d['X'], dtype=np.float32)
    d['y'] = np.array(d['y'])
    d['init'] = np.array(d['init'], dtype=np.float64)
    d['odds_1min'] = np.array(d['odds_1min'])
    d['odds_conf'] = np.array(d['odds_conf'])
    for cn in winsorize_cols:
        if cn in FNAMES:
            ci = FNAMES.index(cn)
            col = d['X'][:, ci]
            mu = col.mean()
            sd = col.std()
            if sd > 0:
                d['X'][:, ci] = np.clip(col, mu - 3 * sd, mu + 3 * sd)
    print(f"  {y}: {len(d['X']):,}", flush=True)

print(f"\n  特徴量: {FNAMES}")
print(f"  特徴量数: {len(FNAMES)}（move_5to1除外済み）")

params = {
    'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
    'num_leaves': 7, 'min_data_in_leaf': 2000, 'feature_fraction': 0.5,
    'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0,
    'verbose': -1, 'seed': 42
}


# === τフィット関数 ===
def fit_tau_on_year(model, year_data, fix_b=None):
    X = year_data['X']; y = year_data['y']; init = year_data['init']; meta = year_data['meta']
    raw = model.predict(X, raw_score=True)
    race_data = defaultdict(list)
    for i, (rid, hn) in enumerate(meta):
        race_data[rid].append(i)

    if fix_b is not None:
        # bを固定してτだけフィット
        def neg_ll(params_arr):
            tau = params_arr[0]
            nll = 0; n = 0
            for rid, idxs in race_data.items():
                ys = y[idxs]; wi = np.where(ys == 1)[0]
                if len(wi) == 0: continue
                s = fix_b * init[idxs] + tau * raw[idxs]
                s -= s.max(); exp_s = np.exp(s)
                nll -= (s[wi[0]] - math.log(exp_s.sum()))
                n += 1
            return nll / n if n > 0 else 999
        res = minimize(neg_ll, x0=[1.0], method='Nelder-Mead', options={'maxiter': 1000})
        return fix_b, res.x[0]
    else:
        def neg_ll(params_arr):
            b, tau = params_arr
            nll = 0; n = 0
            for rid, idxs in race_data.items():
                ys = y[idxs]; wi = np.where(ys == 1)[0]
                if len(wi) == 0: continue
                s = b * init[idxs] + tau * raw[idxs]
                s -= s.max(); exp_s = np.exp(s)
                nll -= (s[wi[0]] - math.log(exp_s.sum()))
                n += 1
            return nll / n if n > 0 else 999
        res = minimize(neg_ll, x0=[1.0, 1.0], method='Nelder-Mead', options={'maxiter': 1000})
        return res.x[0], res.x[1]


# === ラグ版バックテスト ===
print(f"\n{'=' * 100}")
print("=== 経路B: move_5to1除外 + b=1.0固定 ===")
print(f"{'=' * 100}")

# === 比較: b=free vs b=1.0 ===
for b_mode, b_label in [(None, "b=free"), (1.0, "b=1.0")]:
    print(f"\n--- {b_label} ---")

    # Step 1: 各年のモデルとτを計算
    yearly_models = {}
    yearly_tau = {}

    for ty in range(2017, 2027):
        if ty not in datasets: continue
        train_years = [y for y in range(2015, ty) if y in datasets]
        if not train_years: continue
        X_tr = np.vstack([datasets[y]['X'] for y in train_years])
        y_tr = np.concatenate([datasets[y]['y'] for y in train_years])
        init_tr = np.concatenate([datasets[y]['init'] for y in train_years])
        dtrain = lgb.Dataset(X_tr, y_tr, feature_name=FNAMES, init_score=init_tr)
        model = lgb.train(params, dtrain, num_boost_round=300)
        yearly_models[ty] = model

        b_fit, tau_fit = fit_tau_on_year(model, datasets[ty], fix_b=b_mode)
        yearly_tau[ty] = (b_fit, tau_fit)

    # Step 2: テスト
    print(f"\n  {'year':>4} {'τ_from':>7} {'b':>6} {'τ':>6} {'Δ_τ':>8} {'n_race':>7} | {'EV≥1.1':>7} {'hit':>4} {'rec%':>6} | {'EV≥1.0':>7} {'hit':>4} {'rec%':>6} | {'2-30x':>6} {'hit':>4} {'rec%':>6}")
    print(f"  {'-' * 110}")

    all_bets = []

    for ty in range(2018, 2027):
        if ty not in datasets or ty not in yearly_models: continue
        prev_year = ty - 1
        if prev_year not in yearly_tau: continue

        b_use, tau_use = yearly_tau[prev_year]
        model = yearly_models[ty]
        X_te = datasets[ty]['X']; y_te = datasets[ty]['y']
        init_te = datasets[ty]['init']; meta_te = datasets[ty]['meta']
        odds_1min_te = datasets[ty]['odds_1min']
        raw_te = model.predict(X_te, raw_score=True)

        race_data = defaultdict(list)
        for i, (rid, hn) in enumerate(meta_te):
            race_data[rid].append(i)
        mp_te = np.array([1 / (1 + np.exp(-init_te[i])) for i in range(len(init_te))])

        mkt_nll = 0; tau_nll = 0; n_races = 0

        for rid, idxs in race_data.items():
            ys = y_te[idxs]; wi = np.where(ys == 1)[0]
            if len(wi) == 0: continue
            hns = [meta_te[i][1] for i in idxs]
            winner_hn = hns[wi[0]]
            mp_race = mp_te[idxs]; mp_norm = mp_race / mp_race.sum()
            mkt_nll -= math.log(max(mp_norm[wi[0]], 1e-15))

            s_tau = b_use * init_te[idxs] + tau_use * raw_te[idxs]
            s_tau -= s_tau.max()
            tau_p = np.exp(s_tau) / np.exp(s_tau).sum()
            tau_nll -= math.log(max(tau_p[wi[0]], 1e-15))
            n_races += 1

            # HJC確定オッズで払戻計算
            hjc = hjc_cache.get(rid, {})

            for j, idx in enumerate(idxs):
                o1 = odds_1min_te[idx]
                if o1 <= 0: continue
                ev = tau_p[j] * o1
                is_hit = (hns[j] == winner_hn)
                payout_hjc = hjc.get(hns[j], 0) if is_hit else 0

                all_bets.append({
                    'year': ty, 'ev': ev, 'odds_1min': o1,
                    'model_p': tau_p[j], 'is_hit': is_hit,
                    'payout_hjc': payout_hjc, 'horse_num': hns[j], 'rid': rid
                })

        delta_tau = (mkt_nll - tau_nll) / n_races if n_races > 0 else 0
        yb = [b for b in all_bets if b['year'] == ty]

        def calc_rec(bets_list):
            if not bets_list: return 0, 0, 0
            n = len(bets_list)
            hits = sum(1 for b in bets_list if b['is_hit'])
            invest = n * 100
            payout = sum(b['payout_hjc'] * 100 for b in bets_list if b['is_hit'])
            rec = payout / invest * 100 if invest > 0 else 0
            return n, hits, rec

        ev11 = [b for b in yb if b['ev'] >= 1.1]
        ev10 = [b for b in yb if b['ev'] >= 1.0]
        band = [b for b in yb if b['ev'] >= 1.1 and 2 <= b['odds_1min'] <= 30]

        n11, h11, r11 = calc_rec(ev11)
        n10, h10, r10 = calc_rec(ev10)
        nb, hb, rb = calc_rec(band)

        print(f"  {ty:>4} {prev_year:>7} {b_use:>5.2f} {tau_use:>5.2f} {delta_tau:>+7.4f} {n_races:>7} | {n11:>7} {h11:>4} {r11:>5.1f}% | {n10:>7} {h10:>4} {r10:>5.1f}% | {nb:>6} {hb:>4} {rb:>5.1f}%")

    # 全体集計
    for label, filt_fn in [
        ("EV≥1.10 全体", lambda b: b['ev'] >= 1.1),
        ("EV≥1.10 2-30x", lambda b: b['ev'] >= 1.1 and 2 <= b['odds_1min'] <= 30),
        ("EV≥1.10 2-16x", lambda b: b['ev'] >= 1.1 and 2 <= b['odds_1min'] <= 16),
        ("EV≥1.05 2-30x", lambda b: b['ev'] >= 1.05 and 2 <= b['odds_1min'] <= 30),
        ("EV≥1.00 全体", lambda b: b['ev'] >= 1.0),
    ]:
        fb = [b for b in all_bets if filt_fn(b)]
        if not fb: continue
        n = len(fb); hits = sum(1 for b in fb if b['is_hit'])
        invest = n * 100
        payout = sum(b['payout_hjc'] * 100 for b in fb if b['is_hit'])
        rec = payout / invest * 100 if invest > 0 else 0
        sum_p = sum(b['model_p'] for b in fb)
        print(f"  {label:<20} n={n:>6} hits={hits:>4} 回収率={rec:>6.1f}% 期待的中={sum_p:>.1f} (n={n:,})")

    # オッズ帯別キャリブレーション
    print(f"\n  --- オッズ帯別の実回収率 (EV≥1.0) ---")
    print(f"  {'オッズ帯':>12} {'n':>6} {'hits':>5} {'的中率':>7} {'回収率':>7} {'avg_modelP':>10}")
    bands = [(1, 3), (3, 5), (5, 10), (10, 20), (20, 50), (50, 100), (100, 999)]
    for lo, hi in bands:
        fb = [b for b in all_bets if b['ev'] >= 1.0 and lo <= b['odds_1min'] < hi]
        if not fb: continue
        n = len(fb); hits = sum(1 for b in fb if b['is_hit'])
        invest = n * 100
        payout = sum(b['payout_hjc'] * 100 for b in fb if b['is_hit'])
        rec = payout / invest * 100 if invest > 0 else 0
        avg_p = np.mean([b['model_p'] for b in fb])
        act_rate = hits / n * 100 if n > 0 else 0
        print(f"  {lo:>3}-{hi:<4}x {n:>6} {hits:>5} {act_rate:>6.2f}% {rec:>6.1f}% {avg_p:>9.4f}")


print("\n\nDone!", flush=True)
