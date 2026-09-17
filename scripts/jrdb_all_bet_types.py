# -*- coding: utf-8 -*-
"""全券種バランス調査: 単勝/馬単/馬連/三連単/三連複/ワイド
現行モデル(move_5to3)のv21フレームワーク
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
db.close()
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
grade_map = {'G1': 6, 'G2': 5, 'G3': 4, 'OP': 3, 'L': 2, '3勝': 1, '2勝': 0, '1勝': -1, '未勝利': -2, '新馬': -3, '一般': 0}
tc_map = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
sf_map = {'芝': 0, 'ダート': 1}
TAKEOUT = {'win': 0.20, 'umatan': 0.225, 'umaren': 0.225, 'sanrentan': 0.2725, 'sanrenpuku': 0.25, 'wide': 0.225}

FEAT_KEYS = ['idm_c', 'rider_c', 'total_index', 'expert_resid', 'cyb_c',
             'jockey_t3rate', 'trainer_t3rate', 'horse_runs', 'avg_fp_5',
             'top3_rate', 'last_fp', 'win_rate', 'is_senkou', 'move_5to3']


def stern_harville_full(p):
    """全券種のSH確率を一括計算"""
    n = len(p)
    p2 = p ** LAM2
    p3 = p ** LAM3
    S1 = p.sum()
    S2 = p2.sum()
    S3 = p3.sum()
    # 順列ベース
    umatan = {}      # (i,j) ordered: i=1着, j=2着
    sanrentan = {}   # (i,j,k) ordered: i=1着, j=2着, k=3着
    # 組合せベース
    umaren = defaultdict(float)
    trio = defaultdict(float)
    wide = defaultdict(float)

    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0:
            continue
        for j in range(n):
            if j == i:
                continue
            pij = (p[i] / S1) * (p2[j] / d2)
            umatan[(i, j)] = pij
            umaren[tuple(sorted([i, j]))] += pij
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0:
                continue
            for k in range(n):
                if k in (i, j):
                    continue
                pijk = pij * (p3[k] / d3)
                sanrentan[(i, j, k)] = pijk
                trio[tuple(sorted([i, j, k]))] += pijk

    # ワイド: 2頭が3着以内に入る確率
    # P(i,j both in top3) = sum over k of P(i,j,k in some order in top3)
    for (i, j), p_val in umaren.items():
        # wide(i,j) = sum_k trio(i,j,k)
        pass
    # 直接計算
    for key, p_val in trio.items():
        i, j, k = key
        wide[(i, j)] = wide.get((i, j), 0) + p_val
        wide[(i, k)] = wide.get((i, k), 0) + p_val
        wide[(j, k)] = wide.get((j, k), 0) + p_val

    return umatan, umaren, sanrentan, trio, wide


# === Build datasets ===
print("Building datasets...", flush=True)
js = {}
hh = {}
ts_st = {}
win_ds = {}
WFNAMES = None

# ペア/トリオ用
um_ds = {}; UMFNAMES = None   # 馬連
ut_ds = {}; UTFNAMES = None   # 馬単
tr_ds = {}; TRFNAMES = None   # 三連複
st_ds = {}; STFNAMES = None   # 三連単
wd_ds = {}; WDFNAMES = None   # ワイド

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
                if fp == 1: js[jn]['w'] += 1
                if fp <= 3: js[jn]['t3'] += 1
            if tn:
                if tn not in ts_st:
                    ts_st[tn] = {'r': 0, 'w': 0, 't3': 0}
                ts_st[tn]['r'] += 1
                if fp == 1: ts_st[tn]['w'] += 1
                if fp <= 3: ts_st[tn]['t3'] += 1
            if hid:
                if hid not in hh: hh[hid] = []
                hh[hid].append({'fp': fp, 'dist': dt, 'surface': sf})
                if len(hh[hid]) > 30: hh[hid] = hh[hid][-30:]

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
    o5 = ts_odds[5].get(rid, {})
    odds_mkt = o3 if len(o3) >= len(hl) * 0.8 else sed.get(rid, {})
    has_move = len(o5) >= len(hl) * 0.8 and len(o3) >= len(hl) * 0.8
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
    hjc = hjc_all.get(rid, {})

    umatan_mkt, umaren_mkt, sanrentan_mkt, trio_mkt, wide_mkt = stern_harville_full(mp)
    sorted_h = sorted(odds_mkt.items(), key=lambda x: x[1])
    rank_map = {h: i + 1 for i, (h, o) in enumerate(sorted_h)}

    # Build per-horse features
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
            oo5 = o5.get(h, 0)
            oo3 = o3.get(h, 0)
            f['move_5to3'] = (oo5 - oo3) / oo5 if oo5 > 0 and oo3 > 0 else 0
        else:
            f['move_5to3'] = 0
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

    top8 = [h for h, _ in sorted(odds_mkt.items(), key=lambda x: x[1])[:8]] if odds_mkt else hl[:8]
    top2_fps = sorted([r for r in rl if r['fp'] in (1, 2)], key=lambda x: x['fp'])
    top3_fps = sorted([r for r in rl if r['fp'] in (1, 2, 3)], key=lambda x: x['fp'])

    def make_pair_feats(a, b):
        pf = {}
        f1 = feats_h[a]
        f2 = feats_h[b]
        for k in FEAT_KEYS:
            pf[f'{k}_sum'] = f1.get(k, 0) + f2.get(k, 0)
            pf[f'{k}_diff'] = abs(f1.get(k, 0) - f2.get(k, 0))
        ow1 = f1.get('win_odds_3min', 0)
        ow2 = f2.get('win_odds_3min', 0)
        pf['win_odds_ratio'] = min(ow1, ow2) / max(ow1, ow2) if ow1 > 0 and ow2 > 0 else 0
        pf['win_odds_sum_inv'] = (1 / ow1 + 1 / ow2) if ow1 > 0 and ow2 > 0 else 0
        return pf

    def make_trio_feats(a, b, c):
        pf = {}
        f1, f2, f3 = feats_h[a], feats_h[b], feats_h[c]
        for k in FEAT_KEYS:
            v1, v2, v3 = f1.get(k, 0), f2.get(k, 0), f3.get(k, 0)
            pf[f'{k}_sum'] = v1 + v2 + v3
            pf[f'{k}_spread'] = max(v1, v2, v3) - min(v1, v2, v3)
        odds_list = sorted([f.get('win_odds_3min', 0) for f in [f1, f2, f3] if f.get('win_odds_3min', 0) > 0])
        pf['win_odds_top_ratio'] = odds_list[0] / odds_list[-1] if len(odds_list) >= 2 and odds_list[-1] > 0 else 0
        pf['win_odds_sum_inv'] = sum(1 / o for o in odds_list if o > 0)
        return pf

    # --- 馬連 ---
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
            est_odds = (1 / sh_p) * (1 - TAKEOUT['umaren'])
            pf = make_pair_feats(a, b)
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

    # --- 馬単 ---
    if len(top2_fps) >= 2:
        winner_ut = f'{top2_fps[0]["hn"]}-{top2_fps[1]["hn"]}'
        if year not in ut_ds:
            ut_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': [], 'pop': []}
        for a, b in permutations(top8, 2):
            ai = hl.index(a)
            bi = hl.index(b)
            sh_p = umatan_mkt.get((ai, bi), 0)
            if sh_p <= 0:
                continue
            combo = f'{a}-{b}'
            est_odds = (1 / sh_p) * (1 - TAKEOUT['umatan'])
            pf = make_pair_feats(a, b)
            # Add order feature: first horse features
            pf['first_prob'] = feats_h[a].get('win_prob', 0)
            pf['second_prob'] = feats_h[b].get('win_prob', 0)
            if UTFNAMES is None:
                UTFNAMES = sorted(pf.keys())
            init = math.log(max(sh_p, 1e-15)) - math.log(max(1 - sh_p, 1e-15))
            is_hit = 1 if combo == winner_ut else 0
            pop = min(rank_map.get(a, 99), rank_map.get(b, 99))
            ut_ds[year]['X'].append([pf.get(k, 0) for k in UTFNAMES])
            ut_ds[year]['y'].append(is_hit)
            ut_ds[year]['init'].append(init)
            ut_ds[year]['meta'].append((rid, combo))
            ut_ds[year]['odds'].append(est_odds)
            ut_ds[year]['pop'].append(pop)

    # --- 三連複 ---
    if len(top3_fps) >= 3:
        winner_tr = '-'.join(str(x) for x in sorted([top3_fps[0]['hn'], top3_fps[1]['hn'], top3_fps[2]['hn']]))
        if year not in tr_ds:
            tr_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': [], 'pop': []}
        for a, b, c in combinations(top8, 3):
            ai, bi, ci = hl.index(a), hl.index(b), hl.index(c)
            key = tuple(sorted([ai, bi, ci]))
            sh_p = trio_mkt.get(key, 0)
            if sh_p <= 0:
                continue
            combo = '-'.join(str(x) for x in sorted([a, b, c]))
            est_odds = (1 / sh_p) * (1 - TAKEOUT['sanrenpuku'])
            pf = make_trio_feats(a, b, c)
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

    # --- 三連単 ---
    if len(top3_fps) >= 3:
        winner_st = f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        if year not in st_ds:
            st_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': [], 'pop': []}
        for a, b, c in permutations(top8, 3):
            ai, bi, ci = hl.index(a), hl.index(b), hl.index(c)
            sh_p = sanrentan_mkt.get((ai, bi, ci), 0)
            if sh_p <= 0:
                continue
            combo = f'{a}-{b}-{c}'
            est_odds = (1 / sh_p) * (1 - TAKEOUT['sanrentan'])
            pf = make_trio_feats(a, b, c)
            pf['first_prob'] = feats_h[a].get('win_prob', 0)
            pf['second_prob'] = feats_h[b].get('win_prob', 0)
            pf['third_prob'] = feats_h[c].get('win_prob', 0)
            if STFNAMES is None:
                STFNAMES = sorted(pf.keys())
            init = math.log(max(sh_p, 1e-15)) - math.log(max(1 - sh_p, 1e-15))
            is_hit = 1 if combo == winner_st else 0
            pop = min(rank_map.get(a, 99), rank_map.get(b, 99), rank_map.get(c, 99))
            st_ds[year]['X'].append([pf.get(k, 0) for k in STFNAMES])
            st_ds[year]['y'].append(is_hit)
            st_ds[year]['init'].append(init)
            st_ds[year]['meta'].append((rid, combo))
            st_ds[year]['odds'].append(est_odds)
            st_ds[year]['pop'].append(pop)

    # --- ワイド ---
    if len(top2_fps) >= 2:
        # ワイドの的中: 2頭とも3着以内
        if year not in wd_ds:
            wd_ds[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds': [], 'pop': []}
        for a, b in combinations(top8, 2):
            ai = hl.index(a)
            bi = hl.index(b)
            key = tuple(sorted([ai, bi]))
            sh_p = wide_mkt.get(key, 0)
            if sh_p <= 0:
                continue
            combo = '-'.join(str(x) for x in sorted([a, b]))
            est_odds = (1 / sh_p) * (1 - TAKEOUT['wide'])
            pf = make_pair_feats(a, b)
            if WDFNAMES is None:
                WDFNAMES = sorted(pf.keys())
            init = math.log(max(sh_p, 1e-15)) - math.log(max(1 - sh_p, 1e-15))
            fp_a = fps.get(a, 99)
            fp_b = fps.get(b, 99)
            is_hit = 1 if fp_a <= 3 and fp_b <= 3 else 0
            pop = min(rank_map.get(a, 99), rank_map.get(b, 99))
            wd_ds[year]['X'].append([pf.get(k, 0) for k in WDFNAMES])
            wd_ds[year]['y'].append(is_hit)
            wd_ds[year]['init'].append(init)
            wd_ds[year]['meta'].append((rid, combo))
            wd_ds[year]['odds'].append(est_odds)
            wd_ds[year]['pop'].append(pop)

    do_update()

# Convert
for ds_name, ds_obj in [('win', win_ds), ('umaren', um_ds), ('umatan', ut_ds),
                          ('trio', tr_ds), ('sanrentan', st_ds), ('wide', wd_ds)]:
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

# === WF ===
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
        print(f"    {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")

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
                payout = hjc_all.get(rid2, {}).get(hjc_type, {}).get(
                    str(combo) if isinstance(combo, int) else combo, 0) if is_hit else 0
                pop_val = int(pop_te[idx]) if len(pop_te) > idx else 0
                all_bets.append({'year': test_yr, 'ev': float(ev), 'is_hit': int(is_hit),
                                 'payout': payout, 'odds': o, 'pop': pop_val, 'rid': rid2})
    return all_bets


print("\nRunning WF...", flush=True)
bets_win = run_wf(win_ds, WFNAMES, lgb_w, "単勝", 'win_hjc')
bets_um = run_wf(um_ds, UMFNAMES, lgb_p, "馬連", 'umaren_hjc')
bets_ut = run_wf(ut_ds, UTFNAMES, lgb_p, "馬単", 'umatan_hjc')
bets_tr = run_wf(tr_ds, TRFNAMES, lgb_p, "三連複", 'sanrenpuku_hjc')
bets_st = run_wf(st_ds, STFNAMES, lgb_p, "三連単", 'sanrentan_hjc')
bets_wd = run_wf(wd_ds, WDFNAMES, lgb_p, "ワイド", 'wide_hjc')

# === Results ===
print(f"\n{'=' * 100}")
print("全券種バランス比較（現行モデル move_5to3）")
print(f"{'=' * 100}")

all_results = [
    ('単勝 2-40x', [d for d in bets_win if 2 <= d['odds'] <= 40]),
    ('馬単 全', bets_ut),
    ('馬単 1番人気含む', [d for d in bets_ut if d.get('pop', 99) <= 1]),
    ('馬連 全', bets_um),
    ('馬連 1番人気含む', [d for d in bets_um if d.get('pop', 99) <= 1]),
    ('三連単 全', bets_st),
    ('三連単 1番人気含む', [d for d in bets_st if d.get('pop', 99) <= 1]),
    ('三連複 全', bets_tr),
    ('三連複 1番人気含む', [d for d in bets_tr if d.get('pop', 99) <= 1]),
    ('ワイド 全', bets_wd),
    ('ワイド 1番人気含む', [d for d in bets_wd if d.get('pop', 99) <= 1]),
]

for bt_label, data in all_results:
    if not data:
        print(f"\n  {bt_label}: NO DATA")
        continue
    print(f"\n  {bt_label}:")
    print(f"  {'EV>=':>6} {'n':>8} {'hit':>6} {'hit%':>6} {'rec%':>7} | {'2024':>8} {'2025':>8} {'2026':>8}")
    for ev_th in [0.8, 1.0, 1.1, 1.2, 1.3, 1.5]:
        sub = [d for d in data if d['ev'] >= ev_th]
        if len(sub) < 10:
            continue
        n = len(sub)
        hits = sum(d['is_hit'] for d in sub)
        hr = 100 * hits / n
        inv = n * 100
        pay = sum(d['payout'] * 100 for d in sub if d['is_hit'])
        rec = pay / inv * 100 if inv > 0 else 0
        parts = []
        for yr in [2024, 2025, 2026]:
            ys = [d for d in sub if d['year'] == yr]
            if not ys:
                parts.append('       -')
                continue
            yi = len(ys) * 100
            yp = sum(d['payout'] * 100 for d in ys if d['is_hit'])
            parts.append(f'{yp / yi * 100:>7.1f}%')
        print(f"  {ev_th:>5.1f} {n:>8,} {hits:>6,} {hr:>5.1f}% {rec:>6.1f}% | {' '.join(parts)}")

# === Summary table ===
print(f"\n{'=' * 100}")
print("SUMMARY: EV>=1.2 回収率ランキング")
print(f"{'=' * 100}")
print(f"  {'券種':>20} {'n':>8} {'hit':>6} {'rec%':>7} | {'2024':>8} {'2025':>8} {'2026':>8}")
summary = []
for bt_label, data in all_results:
    sub = [d for d in data if d['ev'] >= 1.2]
    if len(sub) < 10:
        continue
    n = len(sub)
    hits = sum(d['is_hit'] for d in sub)
    inv = n * 100
    pay = sum(d['payout'] * 100 for d in sub if d['is_hit'])
    rec = pay / inv * 100 if inv > 0 else 0
    yr_recs = []
    for yr in [2024, 2025, 2026]:
        ys = [d for d in sub if d['year'] == yr]
        if not ys:
            yr_recs.append(0)
            continue
        yi = len(ys) * 100
        yp = sum(d['payout'] * 100 for d in ys if d['is_hit'])
        yr_recs.append(yp / yi * 100)
    summary.append((bt_label, n, hits, rec, yr_recs))

summary.sort(key=lambda x: -x[3])
for bt_label, n, hits, rec, yr_recs in summary:
    yr_str = ' '.join([f'{r:>7.1f}%' if r > 0 else '       -' for r in yr_recs])
    print(f"  {bt_label:>20} {n:>8,} {hits:>6,} {rec:>6.1f}% | {yr_str}")

print("\nDone!")
