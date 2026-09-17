# -*- coding: utf-8 -*-
"""move_10to3 + shiagari_c の全券種EV回収率シミュレーション
比較: (A) 現行 move_5to3  (B) move_10to3+shiagari_c

券種: 単勝 / 馬連 / 三連複
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
race_dates = {r[0]: r[1] for r in races_raw}
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
    if hs:
        race_horses[rid] = sorted(hs)

ts_odds = {}
for mb in [0, 1, 2, 3, 5, 10]:
    ts_odds[mb] = defaultdict(dict)
    for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=? AND odds>0', (mb,)).fetchall():
        ts_odds[mb][rid][hn] = odds

sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall()
    if oz:
        oz_cache[rid] = {int(r[0]): r[1] for r in oz}

# HJC
hjc_cache = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try:
        hjc_cache[row[0]][int(row[1])] = row[2]
    except:
        pass
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]

# CYB
cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB, 'CYB', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 38:
                continue
            raw = line.decode('ascii', 'replace')
            rid2 = f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
            try:
                hn_i = int(raw[8:10])
                score = int(raw[33:35].strip())
            except:
                continue
            cyb_cache[(rid2, hn_i)] = score

# shiagari_sisu
shia_cache = defaultdict(dict)
for row in db.execute('SELECT race_id, horse_number, shiagari_sisu FROM jrdb_live_data WHERE shiagari_sisu IS NOT NULL').fetchall():
    try:
        shia_cache[row[0]][row[1]] = float(row[2])
    except:
        pass

db.close()
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
grade_map = {'G1': 6, 'G2': 5, 'G3': 4, 'OP': 3, 'L': 2, '3勝': 1, '2勝': 0, '1勝': -1, '未勝利': -2, '新馬': -3, '一般': 0}
tc_map = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
sf_map = {'芝': 0, 'ダート': 1}
TAKEOUT_UMAREN = 0.225
TAKEOUT_TRIO = 0.25


def stern_harville(p):
    n = len(p)
    p2 = p ** LAM2
    p3 = p ** LAM3
    S1 = p.sum()
    S2 = p2.sum()
    S3 = p3.sum()
    umaren = defaultdict(float)
    trio = defaultdict(float)
    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0:
            continue
        for j in range(n):
            if j == i:
                continue
            pij = (p[i] / S1) * (p2[j] / d2)
            umaren[tuple(sorted([i, j]))] += pij
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0:
                continue
            for k in range(n):
                if k in (i, j):
                    continue
                pijk = pij * (p3[k] / d3)
                trio[tuple(sorted([i, j, k]))] += pijk
    return umaren, trio


def run_sim(move_from, move_to, mkt_time, use_shiagari, label):
    """WFシミュレーション実行"""
    js = {}
    hh = {}
    ts_st = {}
    datasets = {}
    FNAMES = None

    for rid, rd, vc, sf, dt in races_raw:
        year = int(rd[:4])

        def do_update():
            for res in result_cache.get(rid, []):
                hn, fp, hid = res['hn'], res['fp'], res['hid']
                ent = entry_cache.get(rid, {}).get(hn, {})
                jn = ent.get('jockey', '')
                tn = ent.get('trainer', '')
                if jn:
                    if jn not in js:
                        js[jn] = {'r': 0, 'w': 0, 't3': 0}
                    js[jn]['r'] += 1
                    if fp == 1:
                        js[jn]['w'] += 1
                    if fp <= 3:
                        js[jn]['t3'] += 1
                if tn:
                    if tn not in ts_st:
                        ts_st[tn] = {'r': 0, 'w': 0, 't3': 0}
                    ts_st[tn]['r'] += 1
                    if fp == 1:
                        ts_st[tn]['w'] += 1
                    if fp <= 3:
                        ts_st[tn]['t3'] += 1
                if hid:
                    if hid not in hh:
                        hh[hid] = []
                    hh[hid].append({'fp': fp, 'dist': dt, 'surface': sf})
                    if len(hh[hid]) > 30:
                        hh[hid] = hh[hid][-30:]

        if year < 2022:
            do_update()
            continue
        if year not in datasets:
            datasets[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds_judge': []}
        hl = race_horses.get(rid, [])
        if len(hl) >= 5:
            rl = result_cache.get(rid, [])
            if rl:
                winners = [r['hn'] for r in rl if r['fp'] == 1]
                if winners and winners[0] in hl:
                    odds_mkt = ts_odds[mkt_time].get(rid, {})
                    if len(odds_mkt) < len(hl) * 0.8:
                        odds_mkt = sed.get(rid, {})
                    inv = np.array([1 / odds_mkt.get(h, 999) for h in hl])
                    s = inv.sum()
                    if s == 0:
                        do_update()
                        continue
                    mp = inv / s
                    mp = mp ** 1.015
                    mp /= mp.sum()

                    o_from = ts_odds[move_from].get(rid, {})
                    o_to = ts_odds[move_to].get(rid, {})
                    has_move = len(o_from) >= len(hl) * 0.8 and len(o_to) >= len(hl) * 0.8

                    entries = entry_cache.get(rid, {})
                    n = len(hl)
                    tc = race_cond.get(rid, '良')
                    grade = race_grade.get(rid) or '一般'
                    idms = [entries.get(h, {}).get('idm') or 50 for h in hl]
                    avg_idm = np.mean(idms)
                    riders = [entries.get(h, {}).get('rider') or 0 for h in hl]
                    avg_rider = np.mean(riders)
                    oz = oz_cache.get(rid, {})
                    mkt_d = odds_mkt
                    oz_inv = {h: 1 / oz[h] if h in oz and oz[h] > 0 else 0 for h in hl}
                    mk_inv = {h: 1 / mkt_d[h] if h in mkt_d and mkt_d[h] > 0 else 0 for h in hl}
                    oz_sum = sum(oz_inv.values()) or 1
                    mk_sum = sum(mk_inv.values()) or 1
                    cyb_scores = [cyb_cache.get((rid, h), 0) for h in hl]
                    avg_cyb = np.mean(cyb_scores) if cyb_scores else 0

                    # shiagari
                    shia_vals = [shia_cache.get(rid, {}).get(h, 0) for h in hl]
                    avg_shia = np.mean(shia_vals) if any(v > 0 for v in shia_vals) else 0

                    for i, h in enumerate(hl):
                        ent = entries.get(h, {})
                        hid = ent.get('hid', '')
                        idm = ent.get('idm') or 50
                        rider = ent.get('rider') or 0
                        jn = ent.get('jockey', '')
                        tn = ent.get('trainer', '')
                        runs = hh.get(hid, [])
                        f = {}
                        f['idm_c'] = idm - avg_idm
                        f['rider_c'] = rider - avg_rider
                        f['total_index'] = ent.get('total') or 0
                        oz_p = oz_inv.get(h, 0) / oz_sum
                        mk_p = mk_inv.get(h, 0) / mk_sum
                        f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0
                        f['cyb_c'] = cyb_cache.get((rid, h), 0) - avg_cyb
                        jst = js.get(jn, {})
                        jr = jst.get('r', 0)
                        f['jockey_t3rate'] = jst.get('t3', 0) / jr if jr >= 30 else -1
                        tst = ts_st.get(tn, {})
                        tr_r = tst.get('r', 0)
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
                            f.update({'avg_fp_5': 8, 'top3_rate': 0, 'last_fp': 8, 'dist_t3rate': -1, 'surf_t3rate': -1, 'trend': 0, 'win_rate': -1})
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
                        if has_move:
                            of = o_from.get(h, 0)
                            ot = o_to.get(h, 0)
                            f['move'] = (of - ot) / of if of > 0 and ot > 0 else 0
                        else:
                            f['move'] = 0
                        if use_shiagari:
                            f['shiagari_c'] = shia_vals[i] - avg_shia
                        if FNAMES is None:
                            FNAMES = sorted(f.keys())
                        datasets[year]['X'].append([f.get(k, 0) for k in FNAMES])
                        datasets[year]['y'].append(1 if h == winners[0] else 0)
                        p = mp[i]
                        datasets[year]['init'].append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))
                        datasets[year]['meta'].append((rid, h))
                        datasets[year]['odds_judge'].append(ts_odds[mkt_time].get(rid, {}).get(h, 0))
        do_update()

    for y in sorted(datasets.keys()):
        d = datasets[y]
        d['X'] = np.array(d['X'], dtype=np.float32)
        d['y'] = np.array(d['y'])
        d['init'] = np.array(d['init'], dtype=np.float64)
        d['odds_judge'] = np.array(d['odds_judge'])
        print(f"  {y}: {len(d['X']):,} samples, {sum(d['y']):,.0f} wins")

    params = {'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
              'num_leaves': 7, 'min_data_in_leaf': 2000, 'feature_fraction': 0.5,
              'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0, 'verbose': -1, 'seed': 42}

    print(f"\n{'=' * 80}")
    print(f"  {label}")
    print(f"  Features: {FNAMES}")
    print(f"{'=' * 80}")

    all_bets = []
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

        # fit b, tau
        X_f = datasets[fit_yr]['X']
        y_f = datasets[fit_yr]['y']
        init_f = datasets[fit_yr]['init']
        meta_f = datasets[fit_yr]['meta']
        raw_f = model.predict(X_f, raw_score=True)
        rd_f = defaultdict(list)
        for i, (rid, hn) in enumerate(meta_f):
            rd_f[rid].append(i)

        def neg_ll(p):
            b, tau = p
            nll = 0
            nr = 0
            for rid2, idxs in rd_f.items():
                ys = y_f[idxs]
                wi = np.where(ys == 1)[0]
                if len(wi) == 0:
                    continue
                s = b * init_f[idxs] + tau * raw_f[idxs]
                s -= s.max()
                nll -= (s[wi[0]] - math.log(np.exp(s).sum()))
                nr += 1
            return nll / nr if nr > 0 else 999

        res = minimize(neg_ll, x0=[1.0, 1.0], method='Nelder-Mead', options={'maxiter': 1000})
        b_use, tau_use = res.x
        print(f"\n  {test_yr}: b={b_use:.3f}, tau={tau_use:.3f}")

        # test
        X_te = datasets[test_yr]['X']
        y_te = datasets[test_yr]['y']
        init_te = datasets[test_yr]['init']
        meta_te = datasets[test_yr]['meta']
        odds_te = datasets[test_yr]['odds_judge']
        raw_te = model.predict(X_te, raw_score=True)
        race_data = defaultdict(list)
        for i, (rid, hn) in enumerate(meta_te):
            race_data[rid].append(i)

        for rid2, idxs in race_data.items():
            ys = y_te[idxs]
            wi = np.where(ys == 1)[0]
            if len(wi) == 0:
                continue
            s = b_use * init_te[idxs] + tau_use * raw_te[idxs]
            s -= s.max()
            tau_p = np.exp(s) / np.exp(s).sum()
            hns = [meta_te[i][1] for i in idxs]
            winner = hns[wi[0]]
            fp_map = result_full.get(rid2, {})

            # SH for multi-bet
            umaren_p, trio_p = stern_harville(tau_p)
            n_h = len(hns)

            # 単勝
            hjc_w = hjc_cache.get(rid2, {})
            for j, idx in enumerate(idxs):
                o = odds_te[idx]
                if o <= 0:
                    continue
                ev = tau_p[j] * o
                is_hit = (hns[j] == winner)
                payout = hjc_w.get(hns[j], 0) if is_hit else 0
                all_bets.append({'year': test_yr, 'bet_type': 'win', 'ev': ev, 'odds': o,
                                 'is_hit': is_hit, 'payout': payout, 'model_p': float(tau_p[j]),
                                 'rid': rid2, 'combo': str(hns[j])})

            # 馬連
            hjc_um = hjc_all.get(rid2, {}).get('umaren_hjc', {})
            for (i_idx, j_idx), prob in umaren_p.items():
                if prob <= 0:
                    continue
                hi, hj = hns[i_idx], hns[j_idx]
                combo_key = f'{min(hi,hj)}-{max(hi,hj)}'
                est_odds = (1 / prob) * (1 - TAKEOUT_UMAREN) if prob > 0 else 0
                if est_odds <= 0:
                    continue
                ev = prob * est_odds
                fp_i = fp_map.get(hi, 99)
                fp_j = fp_map.get(hj, 99)
                is_hit = (fp_i <= 2 and fp_j <= 2)
                payout = hjc_um.get(combo_key, 0) if is_hit else 0
                all_bets.append({'year': test_yr, 'bet_type': 'umaren', 'ev': ev, 'odds': est_odds,
                                 'is_hit': is_hit, 'payout': payout, 'model_p': float(prob),
                                 'rid': rid2, 'combo': combo_key})

            # 三連複
            hjc_tr = hjc_all.get(rid2, {}).get('sanrenpuku_hjc', {})
            for (i_idx, j_idx, k_idx), prob in trio_p.items():
                if prob <= 0:
                    continue
                hi, hj, hk = hns[i_idx], hns[j_idx], hns[k_idx]
                combo_sorted = sorted([hi, hj, hk])
                combo_key = f'{combo_sorted[0]}-{combo_sorted[1]}-{combo_sorted[2]}'
                est_odds = (1 / prob) * (1 - TAKEOUT_TRIO) if prob > 0 else 0
                if est_odds <= 0:
                    continue
                ev = prob * est_odds
                fp_i = fp_map.get(hi, 99)
                fp_j = fp_map.get(hj, 99)
                fp_k = fp_map.get(hk, 99)
                is_hit = (fp_i <= 3 and fp_j <= 3 and fp_k <= 3)
                payout = hjc_tr.get(combo_key, 0) if is_hit else 0
                all_bets.append({'year': test_yr, 'bet_type': 'trio', 'ev': ev, 'odds': est_odds,
                                 'is_hit': is_hit, 'payout': payout, 'model_p': float(prob),
                                 'rid': rid2, 'combo': combo_key})

        # Feature importance
        imp = model.feature_importance(importance_type='gain')
        fi = sorted(zip(FNAMES, imp), key=lambda x: -x[1])
        print(f"  Top features: {', '.join([f'{n}={v:.0f}' for n, v in fi[:8]])}")

    # === Results ===
    print(f"\n{'=' * 80}")
    print(f"  Results: {label}")
    print(f"{'=' * 80}")

    for bt, bt_label in [('win', '単勝'), ('umaren', '馬連'), ('trio', '三連複')]:
        print(f"\n  --- {bt_label} ---")
        bt_bets = [b for b in all_bets if b['bet_type'] == bt]
        if not bt_bets:
            print(f"    No data")
            continue

        for yr in [2024, 2025, 2026, 'ALL']:
            if yr == 'ALL':
                yb = bt_bets
            else:
                yb = [b for b in bt_bets if b['year'] == yr]
            if not yb:
                continue

            print(f"\n    {yr}:")
            if bt == 'win':
                odds_bands = [(2, 40)]
            else:
                odds_bands = [(0, 9999)]  # all

            for o_lo, o_hi in odds_bands:
                for th in [1.05, 1.10, 1.15, 1.20, 1.25, 1.30]:
                    fb = [b for b in yb if b['ev'] >= th and o_lo <= b['odds'] <= o_hi]
                    if not fb:
                        continue
                    n = len(fb)
                    h = sum(1 for b in fb if b['is_hit'])
                    inv_t = n * 100
                    pay_t = sum(b['payout'] * 100 for b in fb if b['is_hit'])
                    rec = pay_t / inv_t * 100 if inv_t > 0 else 0
                    print(f"      EV>={th:.2f} {o_lo}-{o_hi}x: n={n:>6,} hit={h:>4,} rec={rec:>6.1f}%")

    # 1番人気含む馬連・三連複
    print(f"\n  --- 1番人気含む（連系） ---")
    for bt, bt_label in [('umaren', '馬連'), ('trio', '三連複')]:
        bt_bets = [b for b in all_bets if b['bet_type'] == bt]
        # 1番人気 = オッズ最低の馬
        # combo に1番人気が含まれるかチェック
        race_fav = {}
        for b in all_bets:
            if b['bet_type'] == 'win':
                rid = b['rid']
                if rid not in race_fav or b['odds'] < race_fav[rid][1]:
                    race_fav[rid] = (b['combo'], b['odds'])

        fav_bets = []
        for b in bt_bets:
            rid = b['rid']
            if rid in race_fav:
                fav_hn = race_fav[rid][0]
                if fav_hn in b['combo'].split('-'):
                    fav_bets.append(b)

        print(f"\n    {bt_label} (1番人気含む):")
        for yr in [2024, 2025, 2026, 'ALL']:
            yb = fav_bets if yr == 'ALL' else [b for b in fav_bets if b['year'] == yr]
            if not yb:
                continue
            for th in [1.10, 1.15, 1.20]:
                fb = [b for b in yb if b['ev'] >= th]
                if not fb:
                    continue
                n = len(fb)
                h = sum(1 for b in fb if b['is_hit'])
                inv_t = n * 100
                pay_t = sum(b['payout'] * 100 for b in fb if b['is_hit'])
                rec = pay_t / inv_t * 100 if inv_t > 0 else 0
                print(f"      {yr} EV>={th:.2f}: n={n:>5,} hit={h:>4,} rec={rec:>6.1f}%")

    return all_bets


# ============================
# Run both models
# ============================
print("\n" + "=" * 80)
print("Model A: move_5to3 (current production)")
print("=" * 80)
bets_a = run_sim(5, 3, 3, False, "A: move_5to3")

print("\n\n" + "=" * 80)
print("Model B: move_10to3 + shiagari_c")
print("=" * 80)
bets_b = run_sim(10, 3, 3, True, "B: move_10to3 + shiagari_c")

# === Side-by-side comparison ===
print("\n" + "=" * 80)
print("COMPARISON: A vs B")
print("=" * 80)

for bt, bt_label in [('win', '単勝'), ('umaren', '馬連'), ('trio', '三連複')]:
    print(f"\n  {bt_label}:")
    for yr in [2024, 2025, 2026, 'ALL']:
        a = [b for b in bets_a if b['bet_type'] == bt and (yr == 'ALL' or b['year'] == yr)]
        b = [b for b in bets_b if b['bet_type'] == bt and (yr == 'ALL' or b['year'] == yr)]
        if not a and not b:
            continue
        print(f"    {yr}:")
        for th in [1.10, 1.15, 1.20]:
            if bt == 'win':
                fa = [x for x in a if x['ev'] >= th and 2 <= x['odds'] <= 40]
                fb = [x for x in b if x['ev'] >= th and 2 <= x['odds'] <= 40]
            else:
                fa = [x for x in a if x['ev'] >= th]
                fb = [x for x in b if x['ev'] >= th]
            na = len(fa)
            ha = sum(1 for x in fa if x['is_hit'])
            ra = sum(x['payout'] * 100 for x in fa if x['is_hit']) / (na * 100) * 100 if na > 0 else 0
            nb = len(fb)
            hb = sum(1 for x in fb if x['is_hit'])
            rb = sum(x['payout'] * 100 for x in fb if x['is_hit']) / (nb * 100) * 100 if nb > 0 else 0
            diff = rb - ra
            print(f"      EV>={th:.2f}: A={na:>5,} {ra:>6.1f}% | B={nb:>5,} {rb:>6.1f}% | {diff:>+6.1f}%")

print("\nDone!")
