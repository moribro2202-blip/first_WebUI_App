# -*- coding: utf-8 -*-
"""JRDB直前情報の特徴量をPhase 3審査する"""
import sqlite3, numpy as np, sys
from collections import defaultdict
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')
DB_PATH = 'data/jrdb.db'
db = sqlite3.connect(DB_PATH)

rows = db.execute('''
    SELECT
        l.race_id, l.race_date, l.horse_number,
        l.kij_tan_odds,
        l.oikiri_sisu,
        l.shiagari_sisu,
        l.tsogo_sisu,
        l.kehai_code,
        CAST(l.idm_text AS REAL) as idm_val,
        l.chokyo_arrow,
        l.kyusya_arrow,
        l.shiagari_henka,
        l.chokyo_honsu,
        l.weight_diff,
        l.jk_leading,
        l.tn_leading,
        t3.odds as odds_3min,
        t5.odds as odds_5min,
        t10.odds as odds_10min,
        r.finish_position,
        r.win_odds
    FROM jrdb_live_data l
    JOIN ts_win_odds t3 ON l.race_id = t3.race_id AND l.horse_number = t3.horse_number AND t3.minutes_before = 3
    JOIN ts_win_odds t5 ON l.race_id = t5.race_id AND l.horse_number = t5.horse_number AND t5.minutes_before = 5
    JOIN ts_win_odds t10 ON l.race_id = t10.race_id AND l.horse_number = t10.horse_number AND t10.minutes_before = 10
    JOIN results r ON l.race_id = r.race_id AND l.horse_number = r.horse_number
    WHERE t3.odds > 0 AND t5.odds > 0 AND t10.odds > 0
      AND r.finish_position IS NOT NULL AND r.win_odds > 0
    ORDER BY l.race_id, l.horse_number
''').fetchall()

print(f'Total rows: {len(rows):,}')

races = defaultdict(list)
for r in rows:
    races[r[0]].append(r)

print(f'Total races: {len(races):,}')

yr_count = defaultdict(int)
for rid in races:
    yr = races[rid][0][1][:4]
    yr_count[yr] += 1
for yr in sorted(yr_count):
    print(f'  {yr}: {yr_count[yr]:,} races')


def safe_float(v, default=0.0):
    try:
        return float(v) if v is not None else default
    except:
        return default


def build(race_rows):
    n = len(race_rows)
    beta = 1.015
    odds_3 = np.array([r[16] for r in race_rows])
    odds_5 = np.array([r[17] for r in race_rows])
    odds_10 = np.array([r[18] for r in race_rows])
    raw_p = 1.0 / odds_3
    market_p = (raw_p ** beta) / np.sum(raw_p ** beta)
    log_market = np.log(market_p + 1e-12)

    move_5to3 = np.log(odds_5 / odds_3)

    shiagari = np.array([safe_float(r[5]) for r in race_rows])
    shiagari_c = shiagari - np.mean(shiagari)

    oikiri = np.array([safe_float(r[4]) for r in race_rows])
    oikiri_c = oikiri - np.mean(oikiri)

    tsogo = np.array([safe_float(r[6]) for r in race_rows])
    tsogo_c = tsogo - np.mean(tsogo)

    idm = np.array([safe_float(r[8]) for r in race_rows])
    idm_c = idm - np.mean(idm)

    chokyo_arrow = np.array([safe_float(r[9]) for r in race_rows])
    chokyo_arrow_c = chokyo_arrow - np.mean(chokyo_arrow)

    kyusya_arrow = np.array([safe_float(r[10]) for r in race_rows])
    kyusya_arrow_c = kyusya_arrow - np.mean(kyusya_arrow)

    shiagari_henka = np.array([safe_float(r[11]) for r in race_rows])
    shiagari_henka_c = shiagari_henka - np.mean(shiagari_henka)

    chokyo_honsu = np.array([safe_float(r[12]) for r in race_rows])
    chokyo_honsu_c = chokyo_honsu - np.mean(chokyo_honsu)

    weight_diff = np.array([safe_float(r[13]) for r in race_rows])
    weight_diff_c = weight_diff - np.mean(weight_diff)

    jk_leading = np.array([safe_float(r[14]) for r in race_rows])
    jk_leading_c = jk_leading - np.mean(jk_leading)

    tn_leading = np.array([safe_float(r[15]) for r in race_rows])
    tn_leading_c = tn_leading - np.mean(tn_leading)

    kij = np.array([safe_float(r[3], 100) for r in race_rows])
    kij = np.clip(kij, 1, 9999)
    raw_kij_p = 1.0 / kij
    kij_p = raw_kij_p / np.sum(raw_kij_p)
    kij_resid = np.log(kij_p + 1e-12) - log_market

    kehai_map = {'1': 2, '2': 1, '3': 0, '4': -1, '5': -2, '6': -1, '7': 0, '8': 1, '9': 0}
    kehai = np.array([safe_float(kehai_map.get(str(r[7]).strip(), 0)) for r in race_rows])
    kehai_c = kehai - np.mean(kehai)

    training_score = oikiri_c * 0.5 + shiagari_c * 0.5

    winner_idx = None
    for j, r in enumerate(race_rows):
        if r[19] == 1:
            winner_idx = j
            break

    return {
        'log_market': log_market, 'move_5to3': move_5to3,
        'shiagari_c': shiagari_c, 'oikiri_c': oikiri_c,
        'tsogo_c': tsogo_c, 'idm_c': idm_c,
        'chokyo_arrow_c': chokyo_arrow_c, 'kyusya_arrow_c': kyusya_arrow_c,
        'shiagari_henka_c': shiagari_henka_c, 'chokyo_honsu_c': chokyo_honsu_c,
        'weight_diff_c': weight_diff_c,
        'jk_leading_c': jk_leading_c, 'tn_leading_c': tn_leading_c,
        'kij_resid': kij_resid, 'kehai_c': kehai_c,
        'training_score': training_score,
        'winner_idx': winner_idx, 'n': n,
        'confirmed_odds': np.array([r[20] for r in race_rows]),
        'finish': np.array([r[19] for r in race_rows]),
    }


def clogit_ll(params, data, fnames):
    ll = 0.0
    for f in data:
        if f['winner_idx'] is None:
            continue
        s = sum(params[k] * f[fn] for k, fn in enumerate(fnames))
        s_max = np.max(s)
        ll += s[f['winner_idx']] - s_max - np.log(np.sum(np.exp(s - s_max)))
    return -ll


# Build data
race_data = {}
for rid in sorted(races.keys()):
    feat = build(races[rid])
    if feat['winner_idx'] is not None:
        yr = races[rid][0][1][:4]
        race_data[rid] = (yr, feat)

years = sorted(set(v[0] for v in race_data.values()))
yr_map = {}
for yr in years:
    yr_map[yr] = [v[1] for v in race_data.values() if v[0] == yr]

print(f'\nYears: {years}')
for yr in years:
    print(f'  {yr}: {len(yr_map[yr]):,} races')

# === WF pairs ===
wf_pairs = []
for i in range(len(years) - 1):
    train_yrs = years[:i+1]
    test_yr = years[i+1]
    train_d = []
    for ty in train_yrs:
        train_d.extend(yr_map[ty])
    wf_pairs.append((train_yrs, test_yr, train_d, yr_map[test_yr]))

print(f'\nWF splits: {len(wf_pairs)}')
for train_yrs, test_yr, train_d, test_d in wf_pairs:
    print(f'  Train {train_yrs} ({len(train_d):,}) -> Test {test_yr} ({len(test_d):,})')

# === Audit ===
base_fnames = ['log_market', 'move_5to3']

candidates = [
    ('shiagari_c', '仕上がり指数'),
    ('oikiri_c', '追い切り指数'),
    ('tsogo_c', '直前総合指数'),
    ('idm_c', 'IDM'),
    ('kehai_c', '気配コード'),
    ('chokyo_arrow_c', '調教矢印'),
    ('kyusya_arrow_c', '厩舎矢印'),
    ('shiagari_henka_c', '仕上がり変化'),
    ('chokyo_honsu_c', '追切本数'),
    ('weight_diff_c', '馬体重増減'),
    ('jk_leading_c', '騎手リーディング'),
    ('tn_leading_c', '調教師リーディング'),
    ('kij_resid', '基準オッズ残差'),
    ('training_score', '調教複合(追切+仕上)'),
]

print(f'\n=== Phase 3 WF Audit: M1 + candidate ===')
header = f'{"Feature":>22s} |'
for _, test_yr, _, _ in wf_pairs:
    header += f'  {test_yr:>7s} |'
header += ' +count | avg delta'
print(header)
print('-' * len(header))

# M1 baseline
m1_results = {}
for train_yrs, test_yr, train_d, test_d in wf_pairs:
    res = minimize(clogit_ll, [1, 0.5], args=(train_d, base_fnames), method='L-BFGS-B')
    m1_results[test_yr] = -clogit_ll(res.x, test_d, base_fnames) / len(test_d)

line = f'{"M1 (baseline)":>22s} |'
for _, test_yr, _, _ in wf_pairs:
    line += f' {m1_results[test_yr]:>8.4f} |'
print(line)

# Candidates
results_summary = []
for feat_name, feat_label in candidates:
    fnames = base_fnames + [feat_name]
    deltas = []
    line = f'{feat_name:>22s} |'
    for train_yrs, test_yr, train_d, test_d in wf_pairs:
        x0 = np.ones(len(fnames))
        res = minimize(clogit_ll, x0, args=(train_d, fnames), method='L-BFGS-B')
        test_ll = -clogit_ll(res.x, test_d, fnames) / len(test_d)
        delta = test_ll - m1_results[test_yr]
        deltas.append(delta)
        line += f' {delta:>+8.5f} |'

    pos_count = sum(1 for d in deltas if d > 0)
    avg_d = np.mean(deltas)
    line += f'  {pos_count}/{len(deltas)}  | {avg_d:>+.5f}'
    results_summary.append((feat_name, feat_label, pos_count, avg_d, deltas))
    print(line)

# Ranking
print(f'\n=== Ranking ===')
results_summary.sort(key=lambda x: (-x[2], -x[3]))
for i, (fn, fl, pc, ad, deltas) in enumerate(results_summary):
    verdict = 'PASS候補' if pc == len(wf_pairs) else 'FAIL'
    print(f'  {i+1:>2d}. {fn:>22s} ({fl:>12s}) : {pc}/{len(wf_pairs)} years+, avg {ad:>+.6f}  -> {verdict}')

# === PASS候補があればシャッフルテスト ===
pass_candidates = [x for x in results_summary if x[2] == len(wf_pairs)]
if pass_candidates:
    print(f'\n=== Shuffle test for PASS candidates ===')
    np.random.seed(42)
    n_shuffles = 500

    for feat_name, feat_label, pc, ad, deltas in pass_candidates:
        fnames = base_fnames + [feat_name]
        # Use largest WF pair for shuffle test
        train_yrs, test_yr, train_d, test_d = wf_pairs[-1]

        res_m1 = minimize(clogit_ll, [1, 0.5], args=(train_d, base_fnames), method='L-BFGS-B')
        res_cand = minimize(clogit_ll, np.ones(len(fnames)), args=(train_d, fnames), method='L-BFGS-B')
        real_delta = (-clogit_ll(res_cand.x, test_d, fnames) - (-clogit_ll(res_m1.x, test_d, base_fnames))) / len(test_d)

        shuffle_deltas = []
        for s in range(n_shuffles):
            shuffled_train = []
            for f in train_d:
                f2 = dict(f)
                perm = np.random.permutation(f2['n'])
                f2[feat_name] = f2[feat_name][perm]
                shuffled_train.append(f2)
            res_s = minimize(clogit_ll, np.ones(len(fnames)), args=(shuffled_train, fnames), method='L-BFGS-B')

            shuffled_test = []
            for f in test_d:
                f2 = dict(f)
                perm = np.random.permutation(f2['n'])
                f2[feat_name] = f2[feat_name][perm]
                shuffled_test.append(f2)
            sd = (-clogit_ll(res_s.x, shuffled_test, fnames) - (-clogit_ll(res_m1.x, test_d, base_fnames))) / len(test_d)
            shuffle_deltas.append(sd)

        shuffle_deltas = np.array(shuffle_deltas)
        p_val = np.mean(shuffle_deltas >= real_delta)
        print(f'  {feat_name} ({feat_label}):')
        print(f'    real delta: {real_delta:+.6f}')
        print(f'    shuffle mean: {np.mean(shuffle_deltas):+.6f}, std: {np.std(shuffle_deltas):.6f}')
        print(f'    p-value: {p_val:.4f}')
        print(f'    verdict: {"PASS" if p_val < 0.05 else "FAIL"}')
        print(f'    coef: {res_cand.x[-1]:.5f}')
else:
    print(f'\nNo PASS candidates found.')

db.close()
