# -*- coding: utf-8 -*-
"""sire_surface_fitのリーク検定
1. ラグ検定: lag0(現行) vs lag1日 vs lag30日
2. 年別詳細
3. 予測確率 vs 実測的中率
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB)
print("Loading data...", flush=True)

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
race_date_map = {r[0]: r[1] for r in db.execute('SELECT race_id,race_date FROM races').fetchall()}
race_horses = {}
for rid, _, _, _, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)

ts1 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]): r[1] for r in oz}
hjc_cache = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try: hjc_cache[row[0]][int(row[1])] = row[2]
    except: pass

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
    if len(odds_src) < len(hl) * 0.8: odds_src = sed.get(rid, {})
    inv = np.array([1 / odds_src.get(h, 999) for h in hl])
    s = inv.sum()
    if s == 0: return None
    p = inv / s; p = p ** 1.015; p /= p.sum()
    return p


def run_with_lag(lag_days, label):
    """ラグ付きsire統計でバックテスト"""
    js = {}; hh = {}; ts_st = {}

    # ラグ付き種牡馬統計: race_dateベースのスナップショットを作る
    # lag_days=0: 当該レースの直前まで（現行コードと同じ）
    # lag_days=1: 前日まで
    # lag_days=30: 30日前まで

    # 全レースを日付順に処理し、日付ごとにスナップショットを保存
    sire_by_date = {}  # date -> sire_stats のスナップショット
    current_sire = defaultdict(lambda: {'r': 0, 'w': 0, 'turf_r': 0, 'turf_w': 0, 'dirt_r': 0, 'dirt_w': 0})
    prev_date = None

    # まず全レースの結果をsire統計に積む（日付ごとにスナップショット保存）
    for rid, rd, vc, sf, dt in races_raw:
        if prev_date is not None and rd != prev_date:
            # 新しい日付 → 前の日付のスナップショットを保存
            import copy
            sire_by_date[prev_date] = copy.deepcopy(current_sire)

        for res in result_cache.get(rid, []):
            hn, fp, hid = res['hn'], res['fp'], res['hid']
            sire = sire_cache.get(hid)
            if not sire: continue
            current_sire[sire]['r'] += 1
            if fp == 1: current_sire[sire]['w'] += 1
            if sf == '芝':
                current_sire[sire]['turf_r'] += 1
                if fp == 1: current_sire[sire]['turf_w'] += 1
            elif sf == 'ダート':
                current_sire[sire]['dirt_r'] += 1
                if fp == 1: current_sire[sire]['dirt_w'] += 1
        prev_date = rd

    if prev_date:
        import copy
        sire_by_date[prev_date] = copy.deepcopy(current_sire)

    # ラグ付き参照のための日付リスト
    sorted_dates = sorted(sire_by_date.keys())

    def get_sire_stats_at(race_date, lag):
        """race_dateからlag日前の統計を返す"""
        if lag == 0:
            # 当該日付の直前 → 前日のスナップショット
            idx = sorted_dates.index(race_date) if race_date in sorted_dates else -1
            if idx <= 0: return {}
            return sire_by_date[sorted_dates[idx - 1]]
        else:
            try:
                target = (datetime.strptime(race_date, '%Y-%m-%d') - timedelta(days=lag)).strftime('%Y-%m-%d')
            except:
                return {}
            # target以前の最新スナップショット
            best = None
            for d in sorted_dates:
                if d <= target: best = d
                else: break
            if best is None: return {}
            return sire_by_date[best]

    # データセット構築
    datasets = {}
    FNAMES = None

    for rid, rd, vc, sf, dt in races_raw:
        year = int(rd[:4])
        if year < 2015:
            # 統計更新（馬履歴等）
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
            continue

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

                        # ラグ付きsire統計を取得
                        sire_st = get_sire_stats_at(rd, lag_days)

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

                            # sire_surface_fit（ラグ付き、NaN扱い）
                            sire = sire_cache.get(hid)
                            if sire and sire in sire_st:
                                ss = sire_st[sire]
                                if sf == '芝' and ss.get('turf_r', 0) >= 30:
                                    f['sire_surface_fit'] = ss['turf_w'] / ss['turf_r']
                                elif sf == 'ダート' and ss.get('dirt_r', 0) >= 30:
                                    f['sire_surface_fit'] = ss['dirt_w'] / ss['dirt_r']
                                else:
                                    f['sire_surface_fit'] = np.nan  # NaN（LightGBM欠損扱い）
                            else:
                                f['sire_surface_fit'] = np.nan

                            if FNAMES is None:
                                FNAMES = sorted(f.keys())

                            datasets[year]['X'].append([f.get(k, 0) if not (isinstance(f.get(k), float) and math.isnan(f.get(k, 0))) else np.nan for k in FNAMES])
                            datasets[year]['y'].append(1 if h == winners[0] else 0)
                            p = mp[i]
                            datasets[year]['init'].append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))
                            datasets[year]['meta'].append((rid, h))
                            datasets[year]['odds_1min'].append(ts1.get(rid, {}).get(h, 0))

        # 統計更新
        for res in result_cache.get(rid, []):
            hn, fp, hid = res['hn'], res['fp'], res['hid']
            ent = entry_cache.get(rid, {}).get(hn, {})
            jn = ent.get('jockey', ''); tn = ent.get('trainer', '')
            if jn:
                if jn not in js: js[jn] = {'r': 0, 'w': 0, 't3': 0}
                js[jn]['r'] += 1;
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

    # Numpy化
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

    # 学習+テスト
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

        X = datasets[ty]['X']; y = datasets[ty]['y']
        init = datasets[ty]['init']; meta = datasets[ty]['meta']
        raw = model.predict(X, raw_score=True)
        rd_data = defaultdict(list)
        for i, (rid, hn) in enumerate(meta): rd_data[rid].append(i)

        def neg_ll(p):
            tau = p[0]; nll = 0; nr = 0
            for rid2, idxs in rd_data.items():
                ys = y[idxs]; wi = np.where(ys == 1)[0]
                if len(wi) == 0: continue
                s = 1.0 * init[idxs] + tau * raw[idxs]
                s -= s.max(); nll -= (s[wi[0]] - math.log(np.exp(s).sum())); nr += 1
            return nll / nr if nr > 0 else 999
        res = minimize(neg_ll, x0=[1.0], method='Nelder-Mead', options={'maxiter': 500})
        yearly_tau[ty] = res.x[0]

    # 年別テスト
    print(f"\n  --- {label} ---")
    print(f"  {'year':>4} {'Δ_τ':>8} {'n_race':>7} | {'EV≥1.1 2-30x':>15} {'hit':>4} {'rec%':>6} | {'avg_modelP':>10} {'act_hitrate':>11}")

    all_bets = []
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
                all_bets.append({'year': ty, 'ev': ev, 'odds': o1, 'is_hit': is_hit,
                                 'payout': payout, 'model_p': float(tau_p[j])})

        delta = (mkt_nll - tau_nll) / n_races if n_races > 0 else 0
        yb = [b for b in all_bets if b['year'] == ty and b['ev'] >= 1.1 and 2 <= b['odds'] <= 30]
        n_bets = len(yb); hits = sum(1 for b in yb if b['is_hit'])
        invest = n_bets * 100; payout_total = sum(b['payout'] * 100 for b in yb if b['is_hit'])
        rec = payout_total / invest * 100 if invest > 0 else 0
        avg_mp = np.mean([b['model_p'] for b in yb]) if yb else 0
        act_hr = hits / n_bets if n_bets > 0 else 0

        sign = '+' if delta > 0 else ''
        print(f"  {ty:>4} {sign}{delta:.5f} {n_races:>7} | n={n_bets:>5} {hits:>4} {rec:>5.1f}% | {avg_mp:>9.5f} {act_hr:>10.5f}")

    # 全体サマリ
    fb = [b for b in all_bets if b['ev'] >= 1.1 and 2 <= b['odds'] <= 30]
    n_total = len(fb); h_total = sum(1 for b in fb if b['is_hit'])
    inv_total = n_total * 100; pay_total = sum(b['payout'] * 100 for b in fb if b['is_hit'])
    rec_total = pay_total / inv_total * 100 if inv_total > 0 else 0
    avg_mp_all = np.mean([b['model_p'] for b in fb]) if fb else 0
    act_hr_all = h_total / n_total if n_total > 0 else 0
    print(f"  {'ALL':>4} {'':>8} {'':>7} | n={n_total:>5} {h_total:>4} {rec_total:>5.1f}% | {avg_mp_all:>9.5f} {act_hr_all:>10.5f}")
    print(f"  予測P vs 実測: 予測={avg_mp_all:.5f} 実測={act_hr_all:.5f} 比={act_hr_all/avg_mp_all:.2f}" if avg_mp_all > 0 else "")

    # feature importance
    imp_model = yearly_models.get(2026) or yearly_models.get(2025)
    if imp_model:
        imp = imp_model.feature_importance(importance_type='gain')
        top5 = sorted(zip(FNAMES, imp), key=lambda x: -x[1])[:5]
        print(f"  top features: {', '.join(f'{n}={v:.0f}' for n, v in top5)}")

    return all_bets


# === 実行 ===
print(f"\n{'=' * 100}")
print("=== sire_surface_fit ラグ検定 ===")
print(f"{'=' * 100}")

for lag, lbl in [(0, "lag=0 (前日スナップショット)"), (1, "lag=1日"), (30, "lag=30日")]:
    run_with_lag(lag, lbl)

print("\nDone!", flush=True)
