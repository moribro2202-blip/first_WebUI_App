# -*- coding: utf-8 -*-
"""move_5to1なしで市場を上回る特徴量を探索
ベースライン: 経路Bモデル（22特徴量、b=1.0）
各候補特徴量を1つずつ追加し、Δ_τの変化を測定
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
db = sqlite3.connect(DB)
print("Loading data...", flush=True)

# === 基本データ ===
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid, _, _, _, _ in races_raw:
    es = db.execute(
        'SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight,gate_number,info_index '
        'FROM entries WHERE race_id=?', (rid,)
    ).fetchall()
    if es:
        entry_cache[rid] = {e[0]: {
            'hid': e[1], 'jockey': e[2], 'trainer': e[3], 'idm': e[4],
            'total': e[5], 'rider': e[6], 'run_style': e[7], 'weight': e[8],
            'gate': e[9], 'info_index': e[10]
        } for e in es}

result_cache = defaultdict(list)
for row in db.execute(
    'SELECT race_id,horse_number,finish_position,horse_id,last_3f,horse_weight,horse_weight_diff '
    'FROM results WHERE finish_position IS NOT NULL'
).fetchall():
    result_cache[row[0]].append({
        'hn': row[1], 'fp': row[2], 'hid': row[3],
        'last3f': row[4], 'hw': row[5], 'hw_diff': row[6]
    })

race_cond = {r[0]: r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]: r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_date_map = {r[0]: r[1] for r in db.execute('SELECT race_id,race_date FROM races').fetchall()}
race_horses = {}
for rid, _, _, _, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs:
        race_horses[rid] = sorted(hs)

ts1 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds
ts0 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=0 AND odds>0').fetchall():
    ts0[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall()
    if oz:
        oz_cache[rid] = {int(r[0]): r[1] for r in oz}
hjc_cache = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try: hjc_cache[row[0]][int(row[1])] = row[2]
    except: pass

# 血統データ
sire_cache = {}
for row in db.execute('SELECT horse_id, sire FROM horses WHERE sire IS NOT NULL').fetchall():
    sire_cache[row[0]] = row[1]

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
    if s == 0: return None
    p = inv / s; p = p ** 1.015; p /= p.sum()
    return p


# === 拡張統計（馬の履歴に上がり3F・体重も含む） ===
js_global = {}; hh_global = {}; ts_global = {}
# 種牡馬別成績
sire_stats = defaultdict(lambda: {'r': 0, 'w': 0, 't3': 0, 'turf_w': 0, 'turf_r': 0, 'dirt_w': 0, 'dirt_r': 0})


def update_stats(rid, rd, vc, sf, dt):
    for res in result_cache.get(rid, []):
        hn, fp, hid = res['hn'], res['fp'], res['hid']
        ent = entry_cache.get(rid, {}).get(hn, {})
        jn = ent.get('jockey', ''); tn = ent.get('trainer', '')
        if jn:
            if jn not in js_global: js_global[jn] = {'r': 0, 'w': 0, 't3': 0}
            js_global[jn]['r'] += 1
            if fp == 1: js_global[jn]['w'] += 1
            if fp <= 3: js_global[jn]['t3'] += 1
        if tn:
            if tn not in ts_global: ts_global[tn] = {'r': 0, 'w': 0, 't3': 0}
            ts_global[tn]['r'] += 1
            if fp == 1: ts_global[tn]['w'] += 1
            if fp <= 3: ts_global[tn]['t3'] += 1
        if hid:
            if hid not in hh_global: hh_global[hid] = []
            hh_global[hid].append({
                'fp': fp, 'dist': dt, 'surface': sf,
                'cond': race_cond.get(rid, '良'),
                'last3f': res.get('last3f'),
                'hw': res.get('hw'), 'hw_diff': res.get('hw_diff'),
                'date': rd, 'grade': race_grade.get(rid, '一般')
            })
            if len(hh_global[hid]) > 30: hh_global[hid] = hh_global[hid][-30:]
        # 種牡馬統計
        sire = sire_cache.get(hid)
        if sire:
            sire_stats[sire]['r'] += 1
            if fp == 1: sire_stats[sire]['w'] += 1
            if fp <= 3: sire_stats[sire]['t3'] += 1
            if sf == '芝':
                sire_stats[sire]['turf_r'] += 1
                if fp == 1: sire_stats[sire]['turf_w'] += 1
            elif sf == 'ダート':
                sire_stats[sire]['dirt_r'] += 1
                if fp == 1: sire_stats[sire]['dirt_w'] += 1


def build_features(rid, hl, rd, vc, sf, dt, extra_features=None):
    """特徴量構築。extra_features: 追加する特徴量名のリスト"""
    entries = entry_cache.get(rid, {})
    n = len(hl); tc = race_cond.get(rid, '良'); grade = race_grade.get(rid) or '一般'
    idms = [entries.get(h, {}).get('idm') or 50 for h in hl]
    avg_idm = np.mean(idms)
    riders = [entries.get(h, {}).get('rider') or 0 for h in hl]
    avg_rider = np.mean(riders)
    oz = oz_cache.get(rid, {}); mkt = ts1.get(rid, sed.get(rid, {}))
    oz_inv = {h: 1 / oz[h] if h in oz and oz[h] > 0 else 0 for h in hl}
    mk_inv = {h: 1 / mkt[h] if h in mkt and mkt[h] > 0 else 0 for h in hl}
    oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1

    # ペース動態: 逃げ/先行の頭数
    n_senkou = sum(1 for h in hl if entries.get(h, {}).get('run_style', '') in ('逃げ', '先行'))
    senkou_ratio = n_senkou / n if n > 0 else 0

    rows = []
    for h in hl:
        ent = entries.get(h, {}); hid = ent.get('hid', '')
        idm = ent.get('idm') or 50; rider = ent.get('rider') or 0
        jn = ent.get('jockey', ''); tn = ent.get('trainer', '')
        runs = hh_global.get(hid, [])

        f = {}
        # --- ベース22特徴量 ---
        f['idm_c'] = idm - avg_idm
        f['rider_c'] = rider - avg_rider
        f['total_index'] = ent.get('total') or 0
        oz_p = oz_inv.get(h, 0) / oz_sum; mk_p = mk_inv.get(h, 0) / mk_sum
        f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0
        jst = js_global.get(jn, {}); jr = jst.get('r', 0)
        f['jockey_t3rate'] = jst.get('t3', 0) / jr if jr >= 30 else -1
        tst = ts_global.get(tn, {}); tr_r = tst.get('r', 0)
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

        # --- 候補特徴量 ---
        if extra_features:
            # 1. ペース動態
            if 'pace_pressure' in extra_features:
                f['pace_pressure'] = senkou_ratio
            if 'is_senkou_in_crowd' in extra_features:
                f['is_senkou_in_crowd'] = 1 if (ent.get('run_style', '') in ('逃げ', '先行') and n_senkou >= 5) else 0

            # 2. 上がり3F（前走）
            if 'last3f_prev' in extra_features:
                l3fs = [r.get('last3f') for r in runs if r.get('last3f') and r['last3f'] > 0]
                race_l3fs = [res.get('last3f') for res in result_cache.get(rid, []) if res.get('last3f') and res['last3f'] > 0]
                avg_l3f = np.mean(race_l3fs) if race_l3fs else 35
                f['last3f_prev'] = (l3fs[-1] - avg_l3f) if l3fs else 0
            if 'last3f_best' in extra_features:
                l3fs = [r.get('last3f') for r in runs if r.get('last3f') and r['last3f'] > 0]
                f['last3f_best'] = min(l3fs) if l3fs else 40

            # 3. 馬体重変動
            if 'hw_diff_prev' in extra_features:
                diffs = [r.get('hw_diff') for r in runs if r.get('hw_diff') is not None]
                f['hw_diff_prev'] = diffs[-1] if diffs else 0
            if 'hw_trend' in extra_features:
                diffs = [r.get('hw_diff') for r in runs[-3:] if r.get('hw_diff') is not None]
                f['hw_trend'] = np.mean(diffs) if diffs else 0

            # 4. 休養日数
            if 'rest_days' in extra_features:
                if runs and runs[-1].get('date'):
                    try:
                        prev_date = datetime.strptime(runs[-1]['date'], '%Y-%m-%d')
                        this_date = datetime.strptime(rd, '%Y-%m-%d')
                        f['rest_days'] = (this_date - prev_date).days
                    except:
                        f['rest_days'] = -1
                else:
                    f['rest_days'] = -1

            # 5. クラス変動
            if 'class_change' in extra_features:
                if runs:
                    prev_grade = runs[-1].get('grade', '一般')
                    f['class_change'] = grade_map.get(grade, 0) - grade_map.get(prev_grade, 0)
                else:
                    f['class_change'] = 0

            # 6. 枠番（内外）
            if 'gate_group' in extra_features:
                gate = ent.get('gate') or h
                f['gate_group'] = gate / 8 if gate else h / n

            # 7. info_index（JRDBの情報指数）
            if 'info_index' in extra_features:
                f['info_index'] = ent.get('info_index') or 0

            # 8. 種牡馬の馬場適性
            if 'sire_surface_fit' in extra_features:
                sire = sire_cache.get(hid)
                if sire and sire in sire_stats:
                    ss = sire_stats[sire]
                    if sf == '芝' and ss['turf_r'] >= 30:
                        f['sire_surface_fit'] = ss['turf_w'] / ss['turf_r']
                    elif sf == 'ダート' and ss['dirt_r'] >= 30:
                        f['sire_surface_fit'] = ss['dirt_w'] / ss['dirt_r']
                    else:
                        f['sire_surface_fit'] = -1
                else:
                    f['sire_surface_fit'] = -1

            # 9. 連対時の上がり3F平均（末脚の質）
            if 'closing_quality' in extra_features:
                t3_l3f = [r.get('last3f') for r in runs if r['fp'] <= 3 and r.get('last3f') and r['last3f'] > 0]
                f['closing_quality'] = np.mean(t3_l3f) if t3_l3f else -1

            # 10. 前走人気 vs 着順（期待超え/下回り）
            if 'last_overperform' in extra_features:
                if runs and len(runs) >= 1:
                    last = runs[-1]
                    # 着順が頭数の何割か（小さいほど好成績）
                    f['last_overperform'] = -last['fp']  # 単純に前走着順の負値
                else:
                    f['last_overperform'] = 0

        rows.append((h, f))
    return rows


# === テスト関数 ===
def run_test(extra_features, label):
    """指定の追加特徴量でバックテストを実行"""
    global js_global, hh_global, ts_global
    js_global = {}; hh_global = {}; ts_global = {}

    datasets = {}
    FNAMES = None

    for rid, rd, vc, sf, dt in races_raw:
        year = int(rd[:4])
        if year < 2015:
            update_stats(rid, rd, vc, sf, dt); continue
        if year not in datasets:
            datasets[year] = {'X': [], 'y': [], 'init': [], 'meta': [], 'odds_1min': []}
        hl = race_horses.get(rid, [])
        if len(hl) >= 5:
            rl = result_cache.get(rid, [])
            if rl:
                winners = [r['hn'] for r in rl if r['fp'] == 1]
                if winners and winners[0] in hl:
                    mp = get_market_p_1min(rid, hl)
                    if mp is not None:
                        feats = build_features(rid, hl, rd, vc, sf, dt, extra_features=extra_features)
                        if feats:
                            if FNAMES is None: FNAMES = sorted(feats[0][1].keys())
                            for i, (hn, f_dict) in enumerate(feats):
                                datasets[year]['X'].append([f_dict.get(k, 0) for k in FNAMES])
                                datasets[year]['y'].append(1 if hn == winners[0] else 0)
                                p = mp[i]
                                datasets[year]['init'].append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))
                                datasets[year]['meta'].append((rid, hn))
                                datasets[year]['odds_1min'].append(ts1.get(rid, {}).get(hn, 0))
        update_stats(rid, rd, vc, sf, dt)

    for y in sorted(datasets.keys()):
        d = datasets[y]
        d['X'] = np.array(d['X'], dtype=np.float32)
        d['y'] = np.array(d['y'])
        d['init'] = np.array(d['init'], dtype=np.float64)
        d['odds_1min'] = np.array(d['odds_1min'])

    params = {
        'objective': 'binary', 'metric': 'binary_logloss', 'learning_rate': 0.01,
        'num_leaves': 7, 'min_data_in_leaf': 2000, 'feature_fraction': 0.5,
        'bagging_fraction': 0.7, 'bagging_freq': 5, 'lambda_l2': 50.0,
        'verbose': -1, 'seed': 42
    }

    # b=1.0固定でτをフィット
    yearly_models = {}; yearly_tau = {}
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

        # b=1.0固定でτフィット
        X = datasets[ty]['X']; y = datasets[ty]['y']
        init = datasets[ty]['init']; meta = datasets[ty]['meta']
        raw = model.predict(X, raw_score=True)
        race_data = defaultdict(list)
        for i, (rid, hn) in enumerate(meta): race_data[rid].append(i)

        def neg_ll(p):
            tau = p[0]; nll = 0; nr = 0
            for rid2, idxs in race_data.items():
                ys = y[idxs]; wi = np.where(ys == 1)[0]
                if len(wi) == 0: continue
                s = 1.0 * init[idxs] + tau * raw[idxs]
                s -= s.max(); nll -= (s[wi[0]] - math.log(np.exp(s).sum())); nr += 1
            return nll / nr if nr > 0 else 999
        res = minimize(neg_ll, x0=[1.0], method='Nelder-Mead', options={'maxiter': 500})
        yearly_tau[ty] = res.x[0]

    # テスト
    deltas = []; all_bets = []
    for ty in range(2018, 2027):
        if ty not in datasets or ty not in yearly_models or (ty - 1) not in yearly_tau: continue
        tau_use = yearly_tau[ty - 1]
        model = yearly_models[ty]
        X_te = datasets[ty]['X']; y_te = datasets[ty]['y']
        init_te = datasets[ty]['init']; meta_te = datasets[ty]['meta']
        odds_te = datasets[ty]['odds_1min']
        raw_te = model.predict(X_te, raw_score=True)

        race_data = defaultdict(list)
        for i, (rid, hn) in enumerate(meta_te): race_data[rid].append(i)
        mp_te = 1 / (1 + np.exp(-init_te))

        mkt_nll = 0; tau_nll = 0; n_races = 0
        for rid2, idxs in race_data.items():
            ys = y_te[idxs]; wi = np.where(ys == 1)[0]
            if len(wi) == 0: continue
            mp_race = mp_te[idxs]; mp_norm = mp_race / mp_race.sum()
            mkt_nll -= math.log(max(mp_norm[wi[0]], 1e-15))
            s = 1.0 * init_te[idxs] + tau_use * raw_te[idxs]
            s -= s.max(); tau_p = np.exp(s) / np.exp(s).sum()
            tau_nll -= math.log(max(tau_p[wi[0]], 1e-15))
            n_races += 1

            hns = [meta_te[i][1] for i in idxs]
            winner = hns[wi[0]]
            hjc = hjc_cache.get(rid2, {})
            for j, idx in enumerate(idxs):
                o1 = odds_te[idx]
                if o1 <= 0: continue
                ev = tau_p[j] * o1
                is_hit = (hns[j] == winner)
                payout = hjc.get(hns[j], 0) if is_hit else 0
                all_bets.append({'year': ty, 'ev': ev, 'odds': o1, 'is_hit': is_hit, 'payout': payout})

        delta = (mkt_nll - tau_nll) / n_races if n_races > 0 else 0
        deltas.append((ty, delta))

    # 集計
    avg_delta = np.mean([d for _, d in deltas])
    pos_years = sum(1 for _, d in deltas if d > 0)

    # EV≥1.10 2-30x回収率
    fb = [b for b in all_bets if b['ev'] >= 1.10 and 2 <= b['odds'] <= 30]
    n_bets = len(fb); hits = sum(1 for b in fb if b['is_hit'])
    invest = n_bets * 100
    payout = sum(b['payout'] * 100 for b in fb if b['is_hit'])
    rec = payout / invest * 100 if invest > 0 else 0

    # EV≥1.05 2-30x
    fb2 = [b for b in all_bets if b['ev'] >= 1.05 and 2 <= b['odds'] <= 30]
    n2 = len(fb2); h2 = sum(1 for b in fb2 if b['is_hit'])
    inv2 = n2 * 100; pay2 = sum(b['payout'] * 100 for b in fb2 if b['is_hit'])
    rec2 = pay2 / inv2 * 100 if inv2 > 0 else 0

    # feature importance
    imp_model = yearly_models.get(2026) or yearly_models.get(2025)
    if imp_model:
        imp = imp_model.feature_importance(importance_type='gain')
        top_feats = sorted(zip(FNAMES, imp), key=lambda x: -x[1])[:5]
        top_str = ', '.join(f'{n}={v:.0f}' for n, v in top_feats)
    else:
        top_str = ''

    print(f"  {label:<35} Δ_τ={avg_delta:>+.5f} ({pos_years}/9yr+) | EV≥1.1 2-30x: n={n_bets:>4} rec={rec:>5.1f}% | EV≥1.05 2-30x: n={n2:>5} rec={rec2:>5.1f}% | top: {top_str}")

    return avg_delta, rec, FNAMES


# === 探索実行 ===
print(f"\n{'=' * 120}")
print("=== 特徴量探索: move_5to1なし + b=1.0固定 ===")
print(f"{'=' * 120}")
print(f"  {'特徴量構成':<35} {'Δ_τ':>10} {'年+':>6} | {'EV≥1.1 2-30x':>16} | {'EV≥1.05 2-30x':>17} | top features")
print(f"  {'-' * 115}")

# ベースライン
run_test(None, "BASE (22 features)")

# 個別追加テスト
candidates = [
    (['pace_pressure'], "+pace_pressure"),
    (['last3f_best'], "+last3f_best"),
    (['hw_diff_prev'], "+hw_diff_prev"),
    (['rest_days'], "+rest_days"),
    (['class_change'], "+class_change"),
    (['gate_group'], "+gate_group"),
    (['info_index'], "+info_index"),
    (['sire_surface_fit'], "+sire_surface_fit"),
    (['closing_quality'], "+closing_quality"),
    (['last_overperform'], "+last_overperform"),
    (['hw_trend'], "+hw_trend"),
    (['is_senkou_in_crowd'], "+is_senkou_in_crowd"),
    (['last3f_prev'], "+last3f_prev"),
]

for feats, label in candidates:
    run_test(feats, label)

# 有望なものを組み合わせ
combos = [
    (['rest_days', 'last3f_best', 'hw_diff_prev'], "+rest+l3f+hw"),
    (['rest_days', 'last3f_best', 'hw_diff_prev', 'class_change'], "+rest+l3f+hw+class"),
    (['rest_days', 'last3f_best', 'hw_diff_prev', 'sire_surface_fit'], "+rest+l3f+hw+sire"),
    (['rest_days', 'last3f_best', 'hw_diff_prev', 'class_change', 'info_index', 'sire_surface_fit'], "+ALL6"),
    (['pace_pressure', 'rest_days', 'last3f_best', 'hw_diff_prev', 'class_change', 'closing_quality', 'info_index', 'sire_surface_fit', 'gate_group'], "+ALL9"),
]

print(f"\n  --- 組み合わせ ---")
for feats, label in combos:
    run_test(feats, label)

print("\nDone!", flush=True)
