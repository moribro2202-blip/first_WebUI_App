# -*- coding: utf-8 -*-
"""全券種比較: A=move_5to3 vs B=move_10to3+shiagari_c
v21フレームワークベース（ペア/トリオLGBM）
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
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
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
                trio[tuple(sorted([i, j, k]))] += pijk
                pijk = pij * (p3[k] / d3)
                trio[tuple(sorted([i, j, k]))] += pijk
    return umaren, trio


def stern_harville_from_win_probs(p):
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


def build_datasets(move_from, move_to, use_shiagari, label):
    """v21式データセット構築"""
    print(f"\nBuilding: {label}", flush=True)
    js = {}
    hh = {}
    ts_st = {}
    FEAT_KEYS = ['idm_c', 'rider_c', 'total_index', 'expert_resid', 'cyb_c',
                 'jockey_t3rate', 'trainer_t3rate', 'horse_runs', 'avg_fp_5',
                 'top3_rate', 'last_fp', 'win_rate', 'is_senkou', 'move_feat']
    if use_shiagari:
        FEAT_KEYS.append('shiagari_c')

    win_ds = {}
    um_ds = {}
    tr_ds = {}
    WFNAMES = None
    UMFNAMES = None
    TRFNAMES = None

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
        hl = race_horses.get(rid, [])
        if len(hl) < 5:
            do_update()
            continue
        rl = result_cache.get(rid, [])
        if not rl:
            do_update()
            continue
        winners = [r['hn'] for r in rl if r['fp'] == 1]
        if not winners or winners[0] not in hl:
            do_update()
            continue

        o3 = ts_odds[3].get(rid, {})
        o_from = ts_odds[move_from].get(rid, {})
        o_to = ts_odds[move_to].get(rid, {})
        odds_mkt = o3 if len(o3) >= len(hl) * 0.8 else sed.get(rid, {})
        has_move = len(o_from) >= len(hl) * 0.8 and len(o_to) >= len(hl) * 0.8
        entries = entry_cache.get(rid, {})
        n = len(hl)

        inv_arr = np.array([1 / odds_mkt.get(h, 999) for h in hl])
        s = inv_arr.sum()
        if s == 0:
            do_update()
            continue
        mp = inv_arr / s
        mp = mp ** 1.015
        mp /= mp.sum()

        idms = [entries.get(h, {}).get('idm') or 50 for h in hl]
        avg_idm = np.mean(idms)
        riders = [entries.get(h, {}).get('rider') or 0 for h in hl]
        avg_rider = np.mean(riders)
        ozd = oz_cache.get(rid, {})
        mkt_d = odds_mkt
        oz_inv = {h: 1 / ozd[h] if h in ozd and ozd[h] > 0 else 0 for h in hl}
        mk_inv = {h: 1 / mkt_d[h] if h in mkt_d and mkt_d[h] > 0 else 0 for h in hl}
        oz_sum = sum(oz_inv.values()) or 1
        mk_sum = sum(mk_inv.values()) or 1
        cyb_scores = [cyb_cache.get((rid, h), 0) for h in hl]
        avg_cyb = np.mean(cyb_scores) if any(c != 0 for c in cyb_scores) else 0
        fps = result_full.get(rid, {})

        umaren_mkt, trio_mkt = stern_harville_from_win_probs(mp)
        sorted_h = sorted(odds_mkt.items(), key=lambda x: x[1])
        rank_map = {h: i + 1 for i, (h, o) in enumerate(sorted_h)}

        shia_vals = [shia_cache.get(rid, {}).get(h, 0) for h in hl]
        avg_shia = np.mean(shia_vals) if any(v > 0 for v in shia_vals) else 0

        feats_h = {}
        for i, h in enumerate(hl):
            ent = entries.get(h, {})
            hid = ent.get('hid', '')
            f = {}
            f['idm_c'] = (ent.get('idm') or 50) - avg_idm
            f['rider_c'] = (ent.get('rider') or 0) - avg_rider
            f['total_index'] = ent.get('total') or 0
            oz_p = oz_inv.get(h, 0) / oz_sum
            mk_p = mk_inv.get(h, 0) / mk_sum
            f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0
            f['cyb_c'] = cyb_cache.get((rid, h), 0) - avg_cyb
            jn = ent.get('jockey', '')
            tn = ent.get('trainer', '')
            jst = js.get(jn, {})
            f['jockey_t3rate'] = jst.get('t3', 0) / jst['r'] if jst.get('r', 0) >= 30 else -1
            tst = ts_st.get(tn, {})
            f['trainer_t3rate'] = tst.get('t3', 0) / tst['r'] if tst.get('r', 0) >= 30 else -1
            runs = hh.get(hid, [])
            f['horse_runs'] = len(runs)
            if runs:
                rc = runs[-5:]
                f['avg_fp_5'] = np.mean([r['fp'] for r in rc])
                f['top3_rate'] = sum(1 for r in runs if r['fp'] <= 3) / len(runs)
                f['last_fp'] = runs[-1]['fp']
                f['win_rate'] = sum(1 for r in runs if r['fp'] == 1) / len(runs) if len(runs) >= 5 else -1
            else:
                f.update({'avg_fp_5': 8, 'top3_rate': 0, 'last_fp': 8, 'win_rate': -1})
            f['is_senkou'] = 1 if ent.get('run_style', '') in ('逃げ', '先行') else 0
            if has_move:
                of = o_from.get(h, 0)
                ot = o_to.get(h, 0)
                f['move_feat'] = (of - ot) / of if of > 0 and ot > 0 else 0
            else:
                f['move_feat'] = 0
            if use_shiagari:
                f['shiagari_c'] = shia_vals[i] - avg_shia
            f['win_odds_3min'] = o3.get(h, 0)
            f['win_prob'] = mp[i]
            feats_h[h] = f

        # --- 単勝 ---
        if year not in win_ds:
            win_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': []}
        for i, h in enumerate(hl):
            fv = feats_h[h]
            if WFNAMES is None:
                WFNAMES = sorted([k for k in FEAT_KEYS])
            win_ds[year]['X'].append([fv.get(k, 0) for k in WFNAMES])
            win_ds[year]['y'].append(1 if h == winners[0] else 0)
            win_ds[year]['init'].append(math.log(max(mp[i], 1e-15)) - math.log(max(1 - mp[i], 1e-15)))
            win_ds[year]['meta'].append((rid, h))
            win_ds[year]['odds'].append(o3.get(h, 0))

        # --- 馬連 ---
        top8 = [h for h, _ in sorted(odds_mkt.items(), key=lambda x: x[1])[:8]] if odds_mkt else hl[:8]
        top2_fps = sorted([r for r in rl if r['fp'] in (1, 2)], key=lambda x: x['fp'])
        if len(top2_fps) >= 2:
            winner_um = '-'.join(str(x) for x in sorted([top2_fps[0]['hn'], top2_fps[1]['hn']]))
            if year not in um_ds:
                um_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': [], 'pop': []}
            for a, b in combinations(top8, 2):
                ai = hl.index(a)
                bi = hl.index(b)
                key = tuple(sorted([ai, bi]))
                sh_p = umaren_mkt.get(key, 0)
                if sh_p <= 0:
                    continue
                combo = '-'.join(str(x) for x in sorted([a, b]))
                est_odds = (1 / sh_p) * (1 - TAKEOUT_UMAREN)
                pf = {}
                f1 = feats_h[a]
                f2 = feats_h[b]
                for k in FEAT_KEYS:
                    v1 = f1.get(k, 0)
                    v2 = f2.get(k, 0)
                    pf[f'{k}_sum'] = v1 + v2
                    pf[f'{k}_diff'] = abs(v1 - v2)
                ow1 = f1.get('win_odds_3min', 0)
                ow2 = f2.get('win_odds_3min', 0)
                pf['win_odds_ratio'] = min(ow1, ow2) / max(ow1, ow2) if ow1 > 0 and ow2 > 0 else 0
                pf['win_odds_sum_inv'] = (1 / ow1 + 1 / ow2) if ow1 > 0 and ow2 > 0 else 0
                if UMFNAMES is None:
                    UMFNAMES = sorted(pf.keys())
                init = math.log(max(sh_p, 1e-15)) - math.log(max(1 - sh_p, 1e-15))
                is_hit = 1 if combo == winner_um else 0
                pop = min(rank_map.get(a, 99), rank_map.get(b, 99))
                um_ds[year]['X'].append([pf.get(k, 0) for k in UMFNAMES])
                um_ds[year]['y'].append(is_hit)
                um_ds[year]['init'].append(init)
                um_ds[year]['meta'].append((rid, combo))
                um_ds[year]['odds'].append(est_odds)
                um_ds[year]['pop'].append(pop)

        # --- 三連複 ---
        top3_fps = sorted([r for r in rl if r['fp'] in (1, 2, 3)], key=lambda x: x['fp'])
        if len(top3_fps) >= 3:
            winner_tr = '-'.join(str(x) for x in sorted([top3_fps[0]['hn'], top3_fps[1]['hn'], top3_fps[2]['hn']]))
            if year not in tr_ds:
                tr_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': [], 'pop': []}
            for a, b, c in combinations(top8, 3):
                ai = hl.index(a)
                bi = hl.index(b)
                ci = hl.index(c)
                key = tuple(sorted([ai, bi, ci]))
                sh_p = trio_mkt.get(key, 0)
                if sh_p <= 0:
                    continue
                combo = '-'.join(str(x) for x in sorted([a, b, c]))
                est_odds = (1 / sh_p) * (1 - TAKEOUT_TRIO)
                pf = {}
                f1 = feats_h[a]
                f2 = feats_h[b]
                f3 = feats_h[c]
                for k in FEAT_KEYS:
                    v1 = f1.get(k, 0)
                    v2 = f2.get(k, 0)
                    v3 = f3.get(k, 0)
                    pf[f'{k}_sum'] = v1 + v2 + v3
                    pf[f'{k}_spread'] = max(v1, v2, v3) - min(v1, v2, v3)
                odds_list = sorted([f.get('win_odds_3min', 0) for f in [f1, f2, f3] if f.get('win_odds_3min', 0) > 0])
                pf['win_odds_top_ratio'] = odds_list[0] / odds_list[-1] if len(odds_list) >= 2 and odds_list[-1] > 0 else 0
                pf['win_odds_sum_inv'] = sum(1 / o for o in odds_list if o > 0)
                if TRFNAMES is None:
                    TRFNAMES = sorted(pf.keys())
                init = math.log(max(sh_p, 1e-15)) - math.log(max(1 - sh_p, 1e-15))
                is_hit = 1 if combo == winner_tr else 0
                pop = min(rank_map.get(a, 99), rank_map.get(b, 99), rank_map.get(c, 99))
                tr_ds[year]['X'].append([pf.get(k, 0) for k in TRFNAMES])
                tr_ds[year]['y'].append(is_hit)
                tr_ds[year]['init'].append(init)
                tr_ds[year]['meta'].append((rid, combo))
                tr_ds[year]['odds'].append(est_odds)
                tr_ds[year]['pop'].append(pop)
        do_update()

    for ds_name, ds_obj in [('win', win_ds), ('umaren', um_ds), ('trio', tr_ds)]:
        for y in sorted(ds_obj.keys()):
            d = ds_obj[y]
            d['X'] = np.array(d['X'], dtype=np.float32)
            d['y'] = np.array(d['y'])
            d['init'] = np.array(d['init'], dtype=np.float64)
            d['odds'] = np.array(d['odds'])
            if 'pop' in d:
                d['pop'] = np.array(d['pop'])
        sizes = ', '.join(str(y) + ':' + str(len(ds_obj[y]['X'])) for y in sorted(ds_obj.keys()))
        print(f"  {ds_name}: {sizes}")

    return win_ds, um_ds, tr_ds, WFNAMES, UMFNAMES, TRFNAMES


lgb_w = {'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
          'num_leaves': 7, 'min_data_in_leaf': 2000, 'feature_fraction': 0.5,
          'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0, 'verbose': -1, 'seed': 42}
lgb_p = {'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
          'num_leaves': 15, 'min_data_in_leaf': 5000, 'feature_fraction': 0.5,
          'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0, 'verbose': -1, 'seed': 42}


def run_wf(ds, fnames, params, label, hjc_type):
    print(f"\n  WF: {label}", flush=True)
    all_bets = []
    for test_yr in [2024, 2025, 2026]:
        train_yrs = [y for y in range(2022, test_yr) if y in ds]
        fit_yr = test_yr - 1
        if not train_yrs or fit_yr not in ds or test_yr not in ds:
            continue
        X_tr = np.vstack([ds[y]['X'] for y in train_yrs])
        y_tr = np.concatenate([ds[y]['y'] for y in train_yrs])
        init_tr = np.concatenate([ds[y]['init'] for y in train_yrs])
        model = lgb.train(params, lgb.Dataset(X_tr, y_tr, feature_name=fnames, init_score=init_tr), num_boost_round=300)
        X_f = ds[fit_yr]['X']
        y_f = ds[fit_yr]['y']
        init_f = ds[fit_yr]['init']
        raw_f = model.predict(X_f, raw_score=True)
        rd_f = defaultdict(list)
        for i, m in enumerate(ds[fit_yr]['meta']):
            rd_f[m[0]].append(i)

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

        X_te = ds[test_yr]['X']
        y_te = ds[test_yr]['y']
        init_te = ds[test_yr]['init']
        meta_te = ds[test_yr]['meta']
        odds_te = ds[test_yr]['odds']
        pop_te = ds[test_yr].get('pop', np.zeros(len(y_te)))
        raw_te = model.predict(X_te, raw_score=True)
        rd_te = defaultdict(list)
        for i, m in enumerate(meta_te):
            rd_te[m[0]].append(i)
        for rid2, idxs in rd_te.items():
            ys = y_te[idxs]
            wi = np.where(ys == 1)[0]
            if len(wi) == 0:
                continue
            s = b_use * init_te[idxs] + tau_use * raw_te[idxs]
            s -= s.max()
            probs = np.exp(s) / np.exp(s).sum()
            for j, idx in enumerate(idxs):
                combo = meta_te[idx][1]
                o = odds_te[idx]
                ev = probs[j] * o
                is_hit = y_te[idx]
                payout = hjc_all.get(rid2, {}).get(hjc_type, {}).get(str(combo) if isinstance(combo, int) else combo, 0) if is_hit else 0
                pop_val = int(pop_te[idx]) if hasattr(pop_te, '__len__') and len(pop_te) > idx else 0
                all_bets.append({'year': test_yr, 'ev': float(ev), 'is_hit': int(is_hit),
                                 'payout': payout, 'odds': o, 'pop': pop_val, 'rid': rid2})
    return all_bets


def print_results(bets_w, bets_u, bets_t, label):
    print(f"\n{'=' * 90}")
    print(f"  {label}")
    print(f"{'=' * 90}")
    for bt_label, data, odds_filter in [
        ('単勝 2-40x', [d for d in bets_w if 2 <= d['odds'] <= 40], None),
        ('馬連 全', bets_u, None),
        ('馬連 1番人気含む', [d for d in bets_u if d.get('pop', 99) <= 1], None),
        ('三連複 全', bets_t, None),
        ('三連複 1番人気含む', [d for d in bets_t if d.get('pop', 99) <= 1], None),
    ]:
        if not data:
            continue
        print(f"\n  {bt_label}:")
        print(f"  {'EV>=':>6} {'n':>7} {'hit':>5} {'rec%':>7} | {'2024':>8} {'2025':>8} {'2026':>8}")
        for ev_th in [0.8, 1.0, 1.1, 1.2, 1.3]:
            sub = [d for d in data if d['ev'] >= ev_th]
            if len(sub) < 10:
                continue
            n = len(sub)
            hits = sum(d['is_hit'] for d in sub)
            inv = n * 100
            pay = sum(d['payout'] * 100 for d in sub if d['is_hit'])
            rec = pay / inv * 100 if inv > 0 else 0
            parts = []
            for yr in [2024, 2025, 2026]:
                ys = [d for d in sub if d['year'] == yr]
                if not ys:
                    parts.append('     -  ')
                    continue
                yi = len(ys) * 100
                yp = sum(d['payout'] * 100 for d in ys if d['is_hit'])
                parts.append(f'{yp / yi * 100:>7.1f}%')
            print(f"  {ev_th:>5.1f} {n:>7,} {hits:>5,} {rec:>6.1f}% | {' '.join(parts)}")


# ============================
# Model A: move_5to3
# ============================
print("\n" + "=" * 80)
print("Model A: move_5to3")
print("=" * 80)
w_a, u_a, t_a, wf_a, uf_a, tf_a = build_datasets(5, 3, False, "A: move_5to3")
bw_a = run_wf(w_a, wf_a, lgb_w, "単勝 A", 'win_hjc')
bu_a = run_wf(u_a, uf_a, lgb_p, "馬連 A", 'umaren_hjc')
bt_a = run_wf(t_a, tf_a, lgb_p, "三連複 A", 'sanrenpuku_hjc')
print_results(bw_a, bu_a, bt_a, "A: move_5to3 (現行)")

# ============================
# Model B: move_10to3 + shiagari_c
# ============================
print("\n" + "=" * 80)
print("Model B: move_10to3 + shiagari_c")
print("=" * 80)
w_b, u_b, t_b, wf_b, uf_b, tf_b = build_datasets(10, 3, True, "B: move_10to3 + shiagari_c")
bw_b = run_wf(w_b, wf_b, lgb_w, "単勝 B", 'win_hjc')
bu_b = run_wf(u_b, uf_b, lgb_p, "馬連 B", 'umaren_hjc')
bt_b = run_wf(t_b, tf_b, lgb_p, "三連複 B", 'sanrenpuku_hjc')
print_results(bw_b, bu_b, bt_b, "B: move_10to3 + shiagari_c")

# === Comparison ===
print(f"\n{'=' * 90}")
print("COMPARISON A vs B")
print(f"{'=' * 90}")
for bt_label, da, db_data in [
    ('単勝 2-40x', [d for d in bw_a if 2 <= d['odds'] <= 40], [d for d in bw_b if 2 <= d['odds'] <= 40]),
    ('馬連 全', bu_a, bu_b),
    ('馬連 1番人気含む', [d for d in bu_a if d.get('pop', 99) <= 1], [d for d in bu_b if d.get('pop', 99) <= 1]),
    ('三連複 全', bt_a, bt_b),
    ('三連複 1番人気含む', [d for d in bt_a if d.get('pop', 99) <= 1], [d for d in bt_b if d.get('pop', 99) <= 1]),
]:
    print(f"\n  {bt_label}:")
    for ev_th in [1.0, 1.1, 1.2, 1.3]:
        sa = [d for d in da if d['ev'] >= ev_th]
        sb = [d for d in db_data if d['ev'] >= ev_th]
        if len(sa) < 10 and len(sb) < 10:
            continue
        na = len(sa)
        ra = sum(d['payout'] * 100 for d in sa if d['is_hit']) / (na * 100) * 100 if na > 0 else 0
        nb = len(sb)
        rb = sum(d['payout'] * 100 for d in sb if d['is_hit']) / (nb * 100) * 100 if nb > 0 else 0
        diff = rb - ra
        print(f"    EV>={ev_th:.1f}: A n={na:>6,} rec={ra:>6.1f}%  |  B n={nb:>6,} rec={rb:>6.1f}%  |  diff={diff:>+6.1f}%")

print("\nDone!")
