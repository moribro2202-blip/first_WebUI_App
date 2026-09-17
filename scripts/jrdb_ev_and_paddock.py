# -*- coding: utf-8 -*-
"""1) shiagari_c追加のEV回収率シミュレーション
   2) パドック特徴量（気配・馬体・パドック印）の条件付きロジット審査
"""
import sqlite3, numpy as np, sys, re
from collections import defaultdict
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')
DB_PATH = 'data/jrdb.db'
db = sqlite3.connect(DB_PATH)

rows = db.execute('''
    SELECT
        l.race_id, l.race_date, l.horse_number,
        l.shiagari_sisu,
        l.kehai_code,
        l.batai_code,
        l.sirusi_padock,
        t3.odds as odds_3min,
        t5.odds as odds_5min,
        r.finish_position,
        r.win_odds
    FROM jrdb_live_data l
    JOIN ts_win_odds t3 ON l.race_id = t3.race_id AND l.horse_number = t3.horse_number AND t3.minutes_before = 3
    JOIN ts_win_odds t5 ON l.race_id = t5.race_id AND l.horse_number = t5.horse_number AND t5.minutes_before = 5
    JOIN results r ON l.race_id = r.race_id AND l.horse_number = r.horse_number
    WHERE t3.odds > 0 AND t5.odds > 0 AND r.finish_position IS NOT NULL AND r.win_odds > 0
    ORDER BY l.race_id, l.horse_number
''').fetchall()

print(f'Total rows: {len(rows):,}')

races = defaultdict(list)
for r in rows:
    races[r[0]].append(r)
print(f'Races: {len(races):,}')


def sf(v, d=0.0):
    try:
        return float(v) if v is not None else d
    except:
        return d


def kehai_to_num(code):
    """気配コード→数値（良い順）"""
    m = {'状態良': 2, '気合良': 2, '平凡': 0, 'チャカ': -1,
         '不安定': -1, 'イレチ': -2, 'イレ込': -2, '気不足': -1}
    return m.get(str(code).strip(), 0)


def batai_to_num(code):
    """馬体コード→数値（良→良=最良、太/細=悪い）"""
    c = str(code).strip()
    if c in ('良→良', '良'):
        return 1
    elif c in ('余→良', '普→良', '細→良', '太→良'):
        return 2  # 改善
    elif c in ('余→余', '余'):
        return 0
    elif c in ('良→余', '良→普', '良→細', '良→太'):
        return -1  # 悪化
    elif c in ('太→余', '余→太', '太→太'):
        return -1
    elif c in ('普→普', '普'):
        return 0
    else:
        return 0


def padock_sirusi_to_num(s):
    """パドック印→数値スコア"""
    if not s or not str(s).strip():
        return 0
    s = str(s).strip()
    # ◎=5, ○=4, ▲=3, 注=2, △=1, ▽=0, ☆=3
    if s.startswith('◎'):
        return 5
    elif s.startswith('○'):
        return 4
    elif s.startswith('☆'):
        return 3
    elif s.startswith('▲'):
        return 3
    elif s.startswith('注'):
        return 2
    elif s.startswith('△'):
        return 1
    elif s.startswith('▽'):
        return 0
    return 0


def build(race_rows):
    n = len(race_rows)
    beta = 1.015
    o3 = np.array([r[7] for r in race_rows])
    o5 = np.array([r[8] for r in race_rows])
    rp = 1.0 / o3
    mp = (rp ** beta) / np.sum(rp ** beta)
    lm = np.log(mp + 1e-12)
    m53 = np.log(o5 / o3)

    sh = np.array([sf(r[3]) for r in race_rows])
    sh_c = sh - np.mean(sh)

    kehai = np.array([kehai_to_num(r[4]) for r in race_rows], dtype=float)
    kehai_c = kehai - np.mean(kehai)

    batai = np.array([batai_to_num(r[5]) for r in race_rows], dtype=float)
    batai_c = batai - np.mean(batai)

    padock = np.array([padock_sirusi_to_num(r[6]) for r in race_rows], dtype=float)
    padock_c = padock - np.mean(padock)

    # 気配 x 馬体 複合
    # 気配良(>=1) AND 馬体良or改善(>=1) → 高スコア
    kehai_batai = kehai_c * 0.5 + batai_c * 0.5

    # パドック総合 = 気配 + 馬体 + 印
    padock_total = kehai_c * 0.3 + batai_c * 0.3 + padock_c * 0.4

    wi = None
    for j, r in enumerate(race_rows):
        if r[9] == 1:
            wi = j
            break

    return {
        'log_market': lm, 'move_5to3': m53, 'shiagari_c': sh_c,
        'kehai_c': kehai_c, 'batai_c': batai_c, 'padock_c': padock_c,
        'kehai_batai': kehai_batai, 'padock_total': padock_total,
        'winner_idx': wi, 'n': n,
        'odds_3': o3, 'market_p': mp,
        'confirmed_odds': np.array([r[10] for r in race_rows]),
        'finish': np.array([r[9] for r in race_rows]),
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


# Build data
rd = {}
for rid in sorted(races):
    f = build(races[rid])
    if f['winner_idx'] is not None:
        yr = races[rid][0][1][:4]
        rd[rid] = (yr, f)

years = sorted(set(v[0] for v in rd.values()))
ym = {yr: [v[1] for v in rd.values() if v[0] == yr] for yr in years}
print(f'Years: {years}')
for yr in years:
    print(f'  {yr}: {len(ym[yr]):,}')

# =============================================
# Part 1: EV回収率シミュレーション (shiagari_c)
# =============================================
print('\n' + '=' * 70)
print('Part 1: EV回収率シミュレーション')
print('=' * 70)

base = ['log_market', 'move_5to3']
base_shia = ['log_market', 'move_5to3', 'shiagari_c']

# WF: train on years before test_yr
for test_yr in years[1:]:
    train_yrs = [y for y in years if y < test_yr]
    train_d = []
    for y in train_yrs:
        train_d.extend(ym[y])
    test_d = ym[test_yr]

    res_m1 = minimize(cll, [1, 0.5], args=(train_d, base), method='L-BFGS-B')
    res_m1s = minimize(cll, [1, 0.5, 0.01], args=(train_d, base_shia), method='L-BFGS-B')

    print(f'\n--- Test: {test_yr} (train: {train_yrs}, {len(test_d):,} races) ---')
    print(f'  M1 params: mkt={res_m1.x[0]:.3f}, move53={res_m1.x[1]:.3f}')
    print(f'  M1+shia:   mkt={res_m1s.x[0]:.3f}, move53={res_m1s.x[1]:.3f}, shia={res_m1s.x[2]:.4f}')

    print(f'\n  {"EV>=":>6s} | {"M1 bets":>7s} {"win":>4s} {"ROI":>7s} | {"M1+sh bets":>10s} {"win":>4s} {"ROI":>7s} | {"diff":>6s}')

    for thresh in [1.05, 1.10, 1.15, 1.20, 1.25, 1.30]:
        for label, params, fnames in [('M1', res_m1.x, base), ('M1s', res_m1s.x, base_shia)]:
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
            if label == 'M1':
                m1_b, m1_w, m1_r = bets, wins, roi
            else:
                m1s_b, m1s_w, m1s_r = bets, wins, roi

        diff = m1s_r - m1_r
        print(f'  {thresh:.2f}  | {m1_b:>7d} {m1_w:>4d} {m1_r:>6.1f}% | {m1s_b:>10d} {m1s_w:>4d} {m1s_r:>6.1f}% | {diff:>+5.1f}%')


# =============================================
# Part 2: パドック特徴量の条件付きロジット審査
# =============================================
print('\n' + '=' * 70)
print('Part 2: パドック特徴量 WF審査')
print('=' * 70)

candidates = [
    ('kehai_c', '気配コード(数値化)'),
    ('batai_c', '馬体コード(数値化)'),
    ('padock_c', 'パドック印(数値化)'),
    ('kehai_batai', '気配x馬体複合'),
    ('padock_total', 'パドック総合'),
]

wf_pairs = []
for i in range(len(years) - 1):
    train_d = []
    for y in years[:i + 1]:
        train_d.extend(ym[y])
    wf_pairs.append((years[:i + 1], years[i + 1], train_d, ym[years[i + 1]]))

# M1 baseline
m1_res = {}
for _, ty, trd, ted in wf_pairs:
    r = minimize(cll, [1, 0.5], args=(trd, base), method='L-BFGS-B')
    m1_res[ty] = -cll(r.x, ted, base) / len(ted)

# M1+shia baseline
m1s_res = {}
for _, ty, trd, ted in wf_pairs:
    r = minimize(cll, [1, 0.5, 0.01], args=(trd, base_shia), method='L-BFGS-B')
    m1s_res[ty] = -cll(r.x, ted, base_shia) / len(ted)

print(f'\n{"Feature":>22s} |', end='')
for _, ty, _, _ in wf_pairs:
    print(f' {ty:>8s} |', end='')
print(' +cnt | avg delta | vs M1+sh')

# vs M1
print('-' * 100)
line = f'{"M1 (baseline)":>22s} |'
for _, ty, _, _ in wf_pairs:
    line += f' {m1_res[ty]:>8.4f} |'
print(line)

line = f'{"M1+shiagari":>22s} |'
for _, ty, _, _ in wf_pairs:
    d = m1s_res[ty] - m1_res[ty]
    line += f' {d:>+8.5f} |'
print(line)

for fn, fl in candidates:
    # vs M1
    fnames1 = base + [fn]
    # vs M1+shia
    fnames2 = base_shia + [fn]

    deltas1 = []
    deltas2 = []
    line = f'{fn:>22s} |'
    for _, ty, trd, ted in wf_pairs:
        r1 = minimize(cll, np.ones(len(fnames1)), args=(trd, fnames1), method='L-BFGS-B')
        ll1 = -cll(r1.x, ted, fnames1) / len(ted)
        d1 = ll1 - m1_res[ty]
        deltas1.append(d1)

        r2 = minimize(cll, np.ones(len(fnames2)), args=(trd, fnames2), method='L-BFGS-B')
        ll2 = -cll(r2.x, ted, fnames2) / len(ted)
        d2 = ll2 - m1s_res[ty]
        deltas2.append(d2)

        line += f' {d1:>+8.5f} |'

    pc1 = sum(1 for d in deltas1 if d > 0)
    avg1 = np.mean(deltas1)
    pc2 = sum(1 for d in deltas2 if d > 0)
    avg2 = np.mean(deltas2)
    line += f' {pc1}/{len(wf_pairs)} | {avg1:>+.5f}  | {pc2}/{len(wf_pairs)} {avg2:>+.5f}'
    print(line)

# パドック印付きデータだけで再検証（印がない馬=0はノイズ）
print(f'\n=== パドック印あり馬のみで再検証 ===')
rd_padock = {}
for rid in sorted(races):
    # レース内で少なくとも1頭に印がある場合のみ
    has_mark = any(padock_sirusi_to_num(r[6]) > 0 for r in races[rid])
    if not has_mark:
        continue
    f = build(races[rid])
    if f['winner_idx'] is not None:
        yr = races[rid][0][1][:4]
        rd_padock[rid] = (yr, f)

ym_p = {yr: [v[1] for v in rd_padock.values() if v[0] == yr] for yr in years}
print(f'Races with paddock marks:')
for yr in years:
    print(f'  {yr}: {len(ym_p.get(yr, [])):,}')

wf_p = []
for i in range(len(years) - 1):
    td = []
    for y in years[:i + 1]:
        td.extend(ym_p.get(y, []))
    if td and ym_p.get(years[i + 1]):
        wf_p.append((years[:i + 1], years[i + 1], td, ym_p[years[i + 1]]))

if wf_p:
    m1_p = {}
    for _, ty, trd, ted in wf_p:
        r = minimize(cll, [1, 0.5], args=(trd, base), method='L-BFGS-B')
        m1_p[ty] = -cll(r.x, ted, base) / len(ted)

    fn_pc = base + ['padock_c']
    print(f'\n{"":>22s} |', end='')
    for _, ty, _, _ in wf_p:
        print(f' {ty:>8s} |', end='')
    print(' +cnt')

    line = f'{"padock_c (marks only)":>22s} |'
    ds = []
    for _, ty, trd, ted in wf_p:
        r = minimize(cll, np.ones(len(fn_pc)), args=(trd, fn_pc), method='L-BFGS-B')
        ll = -cll(r.x, ted, fn_pc) / len(ted)
        d = ll - m1_p[ty]
        ds.append(d)
        line += f' {d:>+8.5f} |'
    pc = sum(1 for d in ds if d > 0)
    line += f' {pc}/{len(wf_p)}'
    print(line)

db.close()
print('\nDone.')
