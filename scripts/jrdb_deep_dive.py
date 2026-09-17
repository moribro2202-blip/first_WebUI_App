# -*- coding: utf-8 -*-
"""move_10to3 + shiagari_c 深掘り + パドック印二値化"""
import sqlite3, numpy as np, sys
from collections import defaultdict
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')
db = sqlite3.connect('data/jrdb.db')

rows = db.execute('''
    SELECT l.race_id, l.race_date, l.horse_number,
        l.shiagari_sisu, l.sirusi_padock,
        t3.odds, t5.odds, t10.odds,
        r.finish_position, r.win_odds
    FROM jrdb_live_data l
    JOIN ts_win_odds t3 ON l.race_id=t3.race_id AND l.horse_number=t3.horse_number AND t3.minutes_before=3
    JOIN ts_win_odds t5 ON l.race_id=t5.race_id AND l.horse_number=t5.horse_number AND t5.minutes_before=5
    JOIN ts_win_odds t10 ON l.race_id=t10.race_id AND l.horse_number=t10.horse_number AND t10.minutes_before=10
    JOIN results r ON l.race_id=r.race_id AND l.horse_number=r.horse_number
    WHERE t3.odds>0 AND t5.odds>0 AND t10.odds>0 AND r.finish_position IS NOT NULL AND r.win_odds>0
    ORDER BY l.race_id, l.horse_number
''').fetchall()
db.close()

races = defaultdict(list)
for r in rows:
    races[r[0]].append(r)

print(f'Total rows: {len(rows):,}, Races: {len(races):,}')


def sf(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except:
        return d


def has_padock_mark(s):
    """パドック印があるか（二値: 1=あり, 0=なし）"""
    if not s or not str(s).strip():
        return 0
    return 1


def build(rr):
    n = len(rr)
    o3 = np.array([r[5] for r in rr])
    o5 = np.array([r[6] for r in rr])
    o10 = np.array([r[7] for r in rr])
    rp = 1.0 / o3
    mp = (rp ** 1.015) / np.sum(rp ** 1.015)
    lm = np.log(mp + 1e-12)
    m53 = np.log(o5 / o3)
    m10to3 = np.log(o10 / o3)
    m10to5 = np.log(o10 / o5)

    sh = np.array([sf(r[3]) for r in rr])
    sh_c = sh - np.mean(sh)

    # パドック印 二値（中心化）
    pad_bin = np.array([has_padock_mark(r[4]) for r in rr], dtype=float)
    pad_bin_c = pad_bin - np.mean(pad_bin)

    wi = None
    for j, r in enumerate(rr):
        if r[8] == 1:
            wi = j
            break

    return {
        'log_market': lm, 'move_5to3': m53,
        'move_10to3': m10to3, 'move_10to5': m10to5,
        'shiagari_c': sh_c, 'pad_bin_c': pad_bin_c,
        'winner_idx': wi, 'n': n,
        'odds_3': o3, 'market_p': mp,
        'confirmed_odds': np.array([r[9] for r in rr]),
        'finish': np.array([r[8] for r in rr]),
    }


def cll(p, data, fn):
    ll = 0.0
    for f in data:
        if f['winner_idx'] is None:
            continue
        s = sum(p[k] * f[n] for k, n in enumerate(fn))
        sm = np.max(s)
        ll += s[f['winner_idx']] - sm - np.log(np.sum(np.exp(s - sm)))
    return -ll


rd = {}
for rid in sorted(races):
    f = build(races[rid])
    if f['winner_idx'] is not None:
        rd[rid] = (races[rid][0][1][:4], f)

years = sorted(set(v[0] for v in rd.values()))
ym = {yr: [v[1] for v in rd.values() if v[0] == yr] for yr in years}

print(f'Years: {years}')
for yr in years:
    print(f'  {yr}: {len(ym[yr]):,}')

# WF pairs
wf = []
for i in range(len(years) - 1):
    td = []
    for y in years[:i + 1]:
        td.extend(ym[y])
    wf.append((years[:i + 1], years[i + 1], td, ym[years[i + 1]]))

# =============================================
# Part 1: move_10to3 + shiagari_c 深掘り
# =============================================
print('\n' + '=' * 70)
print('Part 1: move_10to3 + shiagari_c')
print('=' * 70)

# Baselines
base_m0 = ['log_market']
base_m1 = ['log_market', 'move_5to3']

m0_ll = {}
m1_ll = {}
for _, ty, trd, ted in wf:
    r0 = minimize(cll, [1.0], args=(trd, base_m0), method='L-BFGS-B')
    m0_ll[ty] = -cll(r0.x, ted, base_m0) / len(ted)
    r1 = minimize(cll, [1.0, 0.5], args=(trd, base_m1), method='L-BFGS-B')
    m1_ll[ty] = -cll(r1.x, ted, base_m1) / len(ted)

# Test models
models = [
    ('M0: market', base_m0),
    ('M0+m53', ['log_market', 'move_5to3']),
    ('M0+m10to3', ['log_market', 'move_10to3']),
    ('M0+m10to3+shia', ['log_market', 'move_10to3', 'shiagari_c']),
    ('M0+m53+shia', ['log_market', 'move_5to3', 'shiagari_c']),
    ('M0+m10to3+m53', ['log_market', 'move_10to3', 'move_5to3']),
    ('M0+m10to3+m53+shia', ['log_market', 'move_10to3', 'move_5to3', 'shiagari_c']),
    ('M0+m10to5+m53', ['log_market', 'move_10to5', 'move_5to3']),
]

print(f'\n{"Model":>25s} |', end='')
for _, ty, _, _ in wf:
    print(f'  {ty:>7s} |', end='')
print(' +cnt | avg vs M0 | params')
print('-' * 130)

for mname, fnames in models:
    ds = []
    coeffs_str = ''
    for _, ty, trd, ted in wf:
        x0 = np.ones(len(fnames))
        r = minimize(cll, x0, args=(trd, fnames), method='L-BFGS-B')
        ll = -cll(r.x, ted, fnames) / len(ted)
        d = ll - m0_ll[ty]
        ds.append(d)
        if ty == years[-1]:
            coeffs_str = ' '.join([f'{fn[:6]}={p:.3f}' for fn, p in zip(fnames, r.x)])
    pc = sum(1 for d in ds if d > 0)
    avg = np.mean(ds)
    line = f'{mname:>25s} |'
    for d in ds:
        line += f' {d:>+8.5f} |'
    line += f' {pc}/{len(wf)} | {avg:>+.5f}  | {coeffs_str}'
    print(line)

# === 半期分割安定性テスト ===
print(f'\n=== move_10to3+shiagari_c: 半期分割安定性 ===')
# 2024H1/H2, 2025H1/H2, 2026H1
halves = {}
for rid, (yr, feat) in rd.items():
    date = races[rid][0][1]
    month = date[5:7]
    half = yr + ('H1' if month <= '06' else 'H2')
    if half not in halves:
        halves[half] = []
    halves[half].append(feat)

half_keys = sorted(halves.keys())
print(f'Halves: {[(k, len(halves[k])) for k in half_keys]}')

fn_test = ['log_market', 'move_10to3', 'shiagari_c']
fn_base = ['log_market']

print(f'\n{"Train":>15s} -> {"Test":>8s} | M0 LL   | M0+m10+sh LL | delta   | m10 coef | sh coef')
print('-' * 90)
for i in range(len(half_keys) - 1):
    train_d = []
    for k in half_keys[:i + 1]:
        train_d.extend(halves[k])
    test_k = half_keys[i + 1]
    test_d = halves[test_k]

    r0 = minimize(cll, [1.0], args=(train_d, fn_base), method='L-BFGS-B')
    ll0 = -cll(r0.x, test_d, fn_base) / len(test_d)

    rt = minimize(cll, np.ones(len(fn_test)), args=(train_d, fn_test), method='L-BFGS-B')
    llt = -cll(rt.x, test_d, fn_test) / len(test_d)
    delta = llt - ll0
    sign = '+' if delta > 0 else '-'

    train_label = '+'.join(half_keys[:i + 1])
    print(f'{train_label:>15s} -> {test_k:>8s} | {ll0:.4f} | {llt:.4f}      | {delta:>+.5f} | {rt.x[1]:>8.4f} | {rt.x[2]:>7.4f}')

# === EV回収率シミュレーション ===
print(f'\n=== EV simulation: move_10to3+shiagari_c vs move_5to3 ===')

for test_yr in years[1:]:
    train_d = []
    for y in years:
        if y < test_yr:
            train_d.extend(ym[y])
    test_d = ym[test_yr]

    # M1: market+move53
    r1 = minimize(cll, [1.0, 0.5], args=(train_d, base_m1), method='L-BFGS-B')
    # M_new: market+move10to3+shiagari
    fn_new = ['log_market', 'move_10to3', 'shiagari_c']
    rn = minimize(cll, np.ones(len(fn_new)), args=(train_d, fn_new), method='L-BFGS-B')
    # M_all: market+move10to3+move53+shiagari
    fn_all = ['log_market', 'move_10to3', 'move_5to3', 'shiagari_c']
    ra = minimize(cll, np.ones(len(fn_all)), args=(train_d, fn_all), method='L-BFGS-B')

    print(f'\n--- Test: {test_yr} ({len(test_d):,} races) ---')
    print(f'  {"EV>=":>6s} | {"M1(m53)":>12s} | {"m10+sh":>12s} | {"m10+m53+sh":>12s}')

    for thresh in [1.10, 1.15, 1.20, 1.25, 1.30]:
        row_parts = []
        for label, params, fnames in [
            ('M1', r1.x, base_m1),
            ('m10+sh', rn.x, fn_new),
            ('m10+m53+sh', ra.x, fn_all),
        ]:
            bets = wins = 0
            total_ret = 0.0
            for feat in test_d:
                n = feat['n']
                s = sum(params[k] * feat[fn] for k, fn in enumerate(fnames))
                sm = np.max(s)
                probs = np.exp(s - sm) / np.sum(np.exp(s - sm))
                for j in range(n):
                    odds = feat['confirmed_odds'][j]
                    if odds < 2 or odds > 40:
                        continue
                    ev = probs[j] * odds
                    if ev >= thresh:
                        bets += 1
                        if feat['finish'][j] == 1:
                            wins += 1
                            total_ret += odds
            roi = 100 * total_ret / bets if bets > 0 else 0
            row_parts.append(f'{bets:>4d} {roi:>6.1f}%')
        print(f'  {thresh:.2f}  | {row_parts[0]:>12s} | {row_parts[1]:>12s} | {row_parts[2]:>12s}')


# =============================================
# Part 2: pad_bin_c (has mark or not)
# =============================================
print('\n' + '=' * 70)
print('Part 2: pad_bin_c (has paddock mark)')
print('=' * 70)

# WF audit
candidates_p2 = [
    ('pad_bin_c', 'pad_bin(0/1)'),
]

# vs M0
print(f'\n=== vs M0 ===')
for fn, fl in candidates_p2:
    fnames = base_m0 + [fn]
    ds = []
    line = f'{fn:>22s} |'
    for _, ty, trd, ted in wf:
        x0 = np.ones(len(fnames))
        r = minimize(cll, x0, args=(trd, fnames), method='L-BFGS-B')
        ll = -cll(r.x, ted, fnames) / len(ted)
        d = ll - m0_ll[ty]
        ds.append(d)
        line += f' {d:>+8.5f} |'
    pc = sum(1 for d in ds if d > 0)
    line += f' {pc}/{len(wf)} avg {np.mean(ds):>+.6f}'
    print(line)

# vs M1
print(f'\n=== vs M1 (market+move53) ===')
for fn, fl in candidates_p2:
    fnames = base_m1 + [fn]
    ds = []
    line = f'{fn:>22s} |'
    for _, ty, trd, ted in wf:
        x0 = np.ones(len(fnames))
        r = minimize(cll, x0, args=(trd, fnames), method='L-BFGS-B')
        ll = -cll(r.x, ted, fnames) / len(ted)
        d = ll - m1_ll[ty]
        ds.append(d)
        line += f' {d:>+8.5f} |'
    pc = sum(1 for d in ds if d > 0)
    line += f' {pc}/{len(wf)} avg {np.mean(ds):>+.6f}'
    print(line)

# vs M0+m10to3+shiagari
print(f'\n=== vs M0+move_10to3+shiagari_c (best model) ===')
fn_best = ['log_market', 'move_10to3', 'shiagari_c']
best_ll = {}
for _, ty, trd, ted in wf:
    r = minimize(cll, np.ones(len(fn_best)), args=(trd, fn_best), method='L-BFGS-B')
    best_ll[ty] = -cll(r.x, ted, fn_best) / len(ted)

for fn, fl in candidates_p2:
    fnames = fn_best + [fn]
    ds = []
    line = f'{fn:>22s} |'
    for _, ty, trd, ted in wf:
        x0 = np.ones(len(fnames))
        r = minimize(cll, x0, args=(trd, fnames), method='L-BFGS-B')
        ll = -cll(r.x, ted, fnames) / len(ted)
        d = ll - best_ll[ty]
        ds.append(d)
        line += f' {d:>+8.5f} |'
    pc = sum(1 for d in ds if d > 0)
    avg = np.mean(ds)
    line += f' {pc}/{len(wf)} avg {avg:>+.6f}'
    print(line)

    # coefficients
    for _, ty, trd, ted in wf:
        r = minimize(cll, np.ones(len(fnames)), args=(trd, fnames), method='L-BFGS-B')
        print(f'  {ty}: ' + ', '.join([f'{fn}={p:.4f}' for fn, p in zip(fnames, r.x)]))

print('\nDone.')
