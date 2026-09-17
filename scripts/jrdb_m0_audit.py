# -*- coding: utf-8 -*-
"""M0(市場のみ)ベースラインで JRDB特徴量を審査（move_5to3なし）"""
import sqlite3, numpy as np, sys
from collections import defaultdict
from scipy.optimize import minimize

sys.stdout.reconfigure(encoding='utf-8')
db = sqlite3.connect('data/jrdb.db')

rows = db.execute('''
    SELECT l.race_id, l.race_date, l.horse_number,
        l.shiagari_sisu, l.oikiri_sisu, l.tsogo_sisu,
        CAST(l.idm_text AS REAL), l.kehai_code, l.batai_code,
        l.chokyo_arrow, l.kyusya_arrow, l.shiagari_henka,
        l.chokyo_honsu, l.weight_diff, l.jk_leading, l.tn_leading,
        l.kij_tan_odds, l.sirusi_padock,
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


def kehai_num(c):
    m = {'状態良': 2, '気合良': 2, '平凡': 0, 'チャカ': -1,
         '不安定': -1, 'イレチ': -2, 'イレ込': -2, '気不足': -1}
    return m.get(str(c).strip(), 0)


def batai_num(c):
    c = str(c).strip()
    if c in ('良→良', '良'):
        return 1
    if c in ('余→良', '普→良', '細→良', '太→良'):
        return 2
    if c in ('余→余', '余'):
        return 0
    if c in ('良→余', '良→普', '良→細', '良→太'):
        return -1
    if c in ('太→余', '余→太', '太→太'):
        return -1
    return 0


def padock_num(s):
    if not s or not str(s).strip():
        return 0
    s = str(s).strip()
    if s.startswith('\u25ce'):
        return 5  # ◎
    if s.startswith('\u25cb'):
        return 4  # ○
    if s.startswith('\u2606'):
        return 3  # ☆
    if s.startswith('\u25b2'):
        return 3  # ▲
    if s.startswith('\u6ce8'):
        return 2  # 注
    if s.startswith('\u25b3'):
        return 1  # △
    if s.startswith('\u25bd'):
        return 0  # ▽
    return 0


def build(rr):
    n = len(rr)
    o3 = np.array([r[18] for r in rr])
    o5 = np.array([r[19] for r in rr])
    o10 = np.array([r[20] for r in rr])
    rp = 1.0 / o3
    mp = (rp ** 1.015) / np.sum(rp ** 1.015)
    lm = np.log(mp + 1e-12)
    m53 = np.log(o5 / o3)
    m10to3 = np.log(o10 / o3)

    def centered(vals):
        a = np.array(vals, dtype=float)
        return a - np.mean(a)

    feats = {
        'log_market': lm,
        'move_5to3': m53,
        'move_10to3': m10to3,
        'shiagari_c': centered([sf(r[3]) for r in rr]),
        'oikiri_c': centered([sf(r[4]) for r in rr]),
        'tsogo_c': centered([sf(r[5]) for r in rr]),
        'idm_c': centered([sf(r[6]) for r in rr]),
        'kehai_c': centered([kehai_num(r[7]) for r in rr]),
        'batai_c': centered([batai_num(r[8]) for r in rr]),
        'chokyo_arrow_c': centered([sf(r[9]) for r in rr]),
        'kyusya_arrow_c': centered([sf(r[10]) for r in rr]),
        'shiagari_henka_c': centered([sf(r[11]) for r in rr]),
        'chokyo_honsu_c': centered([sf(r[12]) for r in rr]),
        'weight_diff_c': centered([sf(r[13]) for r in rr]),
        'jk_leading_c': centered([sf(r[14]) for r in rr]),
        'tn_leading_c': centered([sf(r[15]) for r in rr]),
        'padock_c': centered([padock_num(r[17]) for r in rr]),
    }

    kij = np.clip(np.array([sf(r[16], 100) for r in rr]), 1, 9999)
    kp = 1.0 / kij
    kp = kp / np.sum(kp)
    feats['kij_resid'] = np.log(kp + 1e-12) - lm

    wi = None
    for j, r in enumerate(rr):
        if r[21] == 1:
            wi = j
            break
    feats['winner_idx'] = wi
    feats['n'] = n
    return feats


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

base_m0 = ['log_market']

# M0 baseline
m0 = {}
for _, ty, trd, ted in wf:
    r = minimize(cll, [1.0], args=(trd, base_m0), method='L-BFGS-B')
    m0[ty] = -cll(r.x, ted, base_m0) / len(ted)

# M0+move53 for reference
m0m53 = {}
for _, ty, trd, ted in wf:
    r = minimize(cll, [1.0, 0.5], args=(trd, ['log_market', 'move_5to3']), method='L-BFGS-B')
    m0m53[ty] = -cll(r.x, ted, ['log_market', 'move_5to3']) / len(ted)

candidates = [
    ('move_5to3', 'move_5to3(ref)'),
    ('move_10to3', 'move_10to3'),
    ('shiagari_c', 'shiagari'),
    ('oikiri_c', 'oikiri'),
    ('tsogo_c', 'tsogo'),
    ('idm_c', 'IDM'),
    ('kehai_c', 'kehai'),
    ('batai_c', 'batai'),
    ('padock_c', 'padock_mark'),
    ('chokyo_arrow_c', 'chokyo_arr'),
    ('kyusya_arrow_c', 'kyusya_arr'),
    ('shiagari_henka_c', 'shia_henka'),
    ('chokyo_honsu_c', 'chokyo_hon'),
    ('weight_diff_c', 'weight_diff'),
    ('jk_leading_c', 'jk_leading'),
    ('tn_leading_c', 'tn_leading'),
    ('kij_resid', 'kij_resid'),
]

print(f'\n=== M0 + candidate (1 feature, no move_5to3) ===')
header = f'{"Feature":>22s} |'
for _, ty, _, _ in wf:
    header += f'  {ty:>7s} |'
header += ' +cnt | avg delta | avg coef'
print(header)
print('-' * 110)

results = []
for fn, fl in candidates:
    fnames = base_m0 + [fn]
    ds = []
    coeffs = []
    line = f'{fn:>22s} |'
    for _, ty, trd, ted in wf:
        x0 = np.ones(len(fnames))
        r = minimize(cll, x0, args=(trd, fnames), method='L-BFGS-B')
        ll = -cll(r.x, ted, fnames) / len(ted)
        d = ll - m0[ty]
        ds.append(d)
        coeffs.append(r.x[-1])
        line += f' {d:>+8.5f} |'
    pc = sum(1 for d in ds if d > 0)
    avg = np.mean(ds)
    avg_c = np.mean(coeffs)
    line += f' {pc}/{len(wf)} | {avg:>+.5f}  | {avg_c:>+.4f}'
    results.append((fn, fl, pc, avg, avg_c))
    print(line)

print(f'\n=== Ranking (M0 base) ===')
results.sort(key=lambda x: (-x[2], -x[3]))
for i, (fn, fl, pc, ad, ac) in enumerate(results):
    v = 'PASS' if pc == len(wf) else 'FAIL'
    print(f'  {i + 1:>2d}. {fn:>22s} ({fl:>14s}): {pc}/{len(wf)}, avg {ad:>+.6f}, coef {ac:>+.5f} -> {v}')

# === PASS candidates: combine with move_5to3 ===
pass_list = [x for x in results if x[2] == len(wf) and x[0] != 'move_5to3']
if pass_list:
    print(f'\n=== PASS candidates + move_5to3 (vs M1 baseline) ===')
    header2 = f'{"Combination":>30s} |'
    for _, ty, _, _ in wf:
        header2 += f'  {ty:>7s} |'
    header2 += ' +cnt | avg'
    print(header2)
    print('-' * 100)

    for fn, fl, _, _, _ in pass_list:
        fnames = ['log_market', 'move_5to3', fn]
        ds = []
        line = f'{"move53+" + fn:>30s} |'
        for _, ty, trd, ted in wf:
            r = minimize(cll, np.ones(len(fnames)), args=(trd, fnames), method='L-BFGS-B')
            ll = -cll(r.x, ted, fnames) / len(ted)
            d = ll - m0m53[ty]
            ds.append(d)
            line += f' {d:>+8.5f} |'
        pc = sum(1 for d in ds if d > 0)
        avg = np.mean(ds)
        line += f' {pc}/{len(wf)} | {avg:>+.6f}'
        print(line)

    # Pairs without move_5to3
    if len(pass_list) >= 2:
        print(f'\n=== PASS pairs (no move_5to3, M0 base) ===')
        for i in range(len(pass_list)):
            for j in range(i + 1, len(pass_list)):
                fn1 = pass_list[i][0]
                fn2 = pass_list[j][0]
                fnames = ['log_market', fn1, fn2]
                ds = []
                line = f'{fn1 + "+" + fn2:>30s} |'
                for _, ty, trd, ted in wf:
                    r = minimize(cll, np.ones(len(fnames)), args=(trd, fnames), method='L-BFGS-B')
                    ll = -cll(r.x, ted, fnames) / len(ted)
                    d = ll - m0[ty]
                    ds.append(d)
                    line += f' {d:>+8.5f} |'
                pc = sum(1 for d in ds if d > 0)
                avg = np.mean(ds)
                line += f' {pc}/{len(wf)} | {avg:>+.6f}'
                print(line)

print('\nDone.')
