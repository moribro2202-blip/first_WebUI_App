# -*- coding: utf-8 -*-
"""団子判定 + 複勝切り替え検証
三連複モデルの3頭の勝率差で「団子」を判定し:
  団子 → 複勝3点(300円)
  差あり → 三連単1着固定2点(200円)
"""
# データ構築はjrdb_smart_trifecta.pyと同じ
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

exec(open('scripts/jrdb_smart_trifecta.py','r',encoding='utf-8').read().split('# === 分析1')[0])

race_date_map = {r[0]:r[1] for r in races_raw}

# 複勝HJCデータ
db2 = sqlite3.connect(DB)
hjc_place = defaultdict(dict)
for row in db2.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='place_hjc' AND odds>0").fetchall():
    try: hjc_place[row[0]][int(row[1])] = row[2]
    except: pass
db2.close()

cands = [b for b in trio_bets if b['ev']>=1.0 and b['pop']<=1]
race_cands = defaultdict(list)
for b in cands: race_cands[b['rid']].append(b)

# === 分析1: 団子度と1着予測精度の関係 ===
print('='*100)
print('分析1: 勝率差（団子度）と1着予測精度')
print('='*100)

records = []
for rid, bets in race_cands.items():
    bets_sorted = sorted(bets, key=lambda x:-x['ev'])[:5]
    wp = win_probs_by_race.get(rid, {})
    fps = result_full.get(rid, {})
    place_odds = hjc_place.get(rid, {})

    for b in bets_sorted:
        horses = list(b['horses'])
        trio_probs = [(h, wp.get(h, 0)) for h in horses]
        trio_probs.sort(key=lambda x:-x[1])

        p1 = trio_probs[0][1]  # top1勝率
        p2 = trio_probs[1][1]
        p3 = trio_probs[2][1]
        spread = p1 - p3  # 最大-最小
        gap12 = p1 - p2   # 1位-2位の差

        predicted_1st = trio_probs[0][0]
        actual_1st = None
        first_correct = False
        trio_hit = b['is_hit']

        if trio_hit:
            actual_top3 = sorted([(h, fps.get(h, 99)) for h in horses], key=lambda x:x[1])
            actual_1st = actual_top3[0][0]
            first_correct = (actual_1st == predicted_1st)

        # 複勝の払戻（3頭分）
        place_payout = 0
        if trio_hit:
            for h in horses:
                po = place_odds.get(h, 0)
                if po > 0:
                    place_payout += po * 100  # 各100円

        records.append({
            'rid': rid, 'year': b['year'], 'ev': b['ev'],
            'p1': p1, 'p2': p2, 'p3': p3, 'spread': spread, 'gap12': gap12,
            'trio_hit': trio_hit, 'first_correct': first_correct,
            'payout_st': b['payout_st'], 'payout_trio': b['payout_trio'],
            'place_payout': place_payout, 'horses': horses,
        })

spreads = np.array([r['spread'] for r in records])
print(f'全レコード: {len(records):,}')
print(f'spread(p1-p3): mean={np.mean(spreads):.3f}, median={np.median(spreads):.3f}')
print()

# 団子度の五分位で分析
print(f'{"帯":>15} | {"n":>6} | {"trio的中":>7} {"率":>5} | {"1着正解":>7} {"率":>5} | {"三連単ROI":>8} | {"三連複ROI":>8} | {"複勝ROI":>8}')
print('-'*100)

edges = np.percentile(spreads, [0, 20, 40, 60, 80, 100])
for q in range(5):
    lo, hi = edges[q], edges[q+1]
    if q == 4: sub = [r for r in records if r['spread'] >= lo]
    else: sub = [r for r in records if lo <= r['spread'] < hi]
    n = len(sub)
    trio_hits = [r for r in sub if r['trio_hit']]
    n_hit = len(trio_hits)
    n_1st = sum(1 for r in trio_hits if r['first_correct'])
    hit_rate = 100*n_hit/n if n>0 else 0
    first_rate = 100*n_1st/n_hit if n_hit>0 else 0

    # 三連単1着固定ROI (200円/トリオ)
    inv_st = n * 200
    ret_st = sum(r['payout_st']*100 for r in trio_hits if r['first_correct'])
    roi_st = ret_st/inv_st*100 if inv_st>0 else 0

    # 三連複ROI (100円/トリオ)
    inv_tr = n * 100
    ret_tr = sum(r['payout_trio']*100 for r in trio_hits)
    roi_tr = ret_tr/inv_tr*100 if inv_tr>0 else 0

    # 複勝ROI (300円/トリオ = 3頭×100円)
    inv_pl = n * 300
    ret_pl = sum(r['place_payout'] for r in trio_hits)  # 的中時3頭分
    roi_pl = ret_pl/inv_pl*100 if inv_pl>0 else 0

    label = f'Q{q+1}({lo:.3f}-{hi:.3f})'
    dango = '団子' if q == 0 else '差大' if q == 4 else ''
    print(f'{label:>15} | {n:>6,} | {n_hit:>7,} {hit_rate:>4.1f}% | {n_1st:>7,} {first_rate:>4.1f}% | {roi_st:>7.1f}% | {roi_tr:>7.1f}% | {roi_pl:>7.1f}% {dango}')

# === 分析2: gap12(1位-2位の差)で切り分け ===
print()
print('='*100)
print('分析2: gap12(top1-top2の差)で条件分岐')
print('='*100)
print()
print(f'{"gap12閾値":>10} | {"三連単(差あり)":>30} | {"複勝(団子)":>30} | {"合計":>20}')
print('-'*100)

for th in [0.00, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
    # 差あり → 三連単1着固定(200円)
    st_sub = [r for r in records if r['gap12'] >= th]
    inv_st = len(st_sub) * 200
    ret_st = sum(r['payout_st']*100 for r in st_sub if r['trio_hit'] and r['first_correct'])
    roi_st = ret_st/inv_st*100 if inv_st>0 else 0

    # 団子 → 複勝3点(300円)
    pl_sub = [r for r in records if r['gap12'] < th]
    inv_pl = len(pl_sub) * 300
    ret_pl = sum(r['place_payout'] for r in pl_sub if r['trio_hit'])
    roi_pl = ret_pl/inv_pl*100 if inv_pl>0 else 0

    # 合計
    total_inv = inv_st + inv_pl
    total_ret = ret_st + ret_pl
    total_roi = total_ret/total_inv*100 if total_inv>0 else 0
    total_profit = total_ret - total_inv

    n_st = len(st_sub); n_pl = len(pl_sub)
    print(f'  {th:>7.2f} | n={n_st:>5,} roi={roi_st:>5.1f}% | n={n_pl:>5,} roi={roi_pl:>5.1f}% | roi={total_roi:>5.1f}% profit={total_profit:>+,.0f}円')

# === 分析3: 戦略F — 条件分岐の最適化 ===
print()
print('='*100)
print('分析3: 最適条件分岐 vs 固定戦略')
print('='*100)
print()

# 比較: 全部三連単 vs 全部複勝 vs 最適分岐
strategies = {}

# 全部三連単1着固定
inv = len(records) * 200
ret = sum(r['payout_st']*100 for r in records if r['trio_hit'] and r['first_correct'])
strategies['全部三連単1着固定'] = {'inv': inv, 'ret': ret}

# 全部三連複
inv = len(records) * 100
ret = sum(r['payout_trio']*100 for r in records if r['trio_hit'])
strategies['全部三連複'] = {'inv': inv, 'ret': ret}

# 全部複勝3点
inv = len(records) * 300
ret = sum(r['place_payout'] for r in records if r['trio_hit'])
strategies['全部複勝3点'] = {'inv': inv, 'ret': ret}

# 条件分岐(gap12=0.05)
th = 0.05
inv = sum(200 if r['gap12']>=th else 300 for r in records)
ret = sum(r['payout_st']*100 if r['gap12']>=th and r['first_correct'] else
          r['place_payout'] if r['gap12']<th else 0
          for r in records if r['trio_hit'])
strategies[f'分岐(gap>={th}→三連単,<{th}→複勝)'] = {'inv': inv, 'ret': ret}

# 条件分岐(gap12=0.10)
th = 0.10
inv = sum(200 if r['gap12']>=th else 300 for r in records)
ret = sum(r['payout_st']*100 if r['gap12']>=th and r['first_correct'] else
          r['place_payout'] if r['gap12']<th else 0
          for r in records if r['trio_hit'])
strategies[f'分岐(gap>={th}→三連単,<{th}→複勝)'] = {'inv': inv, 'ret': ret}

# 三連単1着固定 + 複勝3点(両方買い, 500円/トリオ)
inv = len(records) * 500
ret = sum((r['payout_st']*100 if r['first_correct'] else 0) + r['place_payout']
          for r in records if r['trio_hit'])
strategies['三連単+複勝(両方)'] = {'inv': inv, 'ret': ret}

print(f'{"戦略":>35} | {"投資":>10} | {"払戻":>10} | {"利益":>10} | {"ROI":>6} | {"1R費用":>6}')
print('-'*90)
n_r = len(set(r['rid'] for r in records))
for name, s in sorted(strategies.items(), key=lambda x: -(x[1]['ret']/x[1]['inv']) if x[1]['inv']>0 else 0):
    roi = s['ret']/s['inv']*100 if s['inv']>0 else 0
    profit = s['ret'] - s['inv']
    cost_r = s['inv'] / n_r
    print(f'{name:>35} | {s["inv"]:>9,}円 | {s["ret"]:>9,.0f}円 | {profit:>+9,.0f}円 | {roi:>5.1f}% | {cost_r:>5.0f}円')

# === 年別で検証 ===
print()
print('='*100)
print('年別: 条件分岐 vs 固定')
print('='*100)
print()

for yr in [2024, 2025, 2026]:
    yr_recs = [r for r in records if r['year'] == yr]
    if not yr_recs: continue

    # 三連単のみ
    inv1 = len(yr_recs)*200; ret1 = sum(r['payout_st']*100 for r in yr_recs if r['trio_hit'] and r['first_correct'])
    # 複勝のみ
    inv2 = len(yr_recs)*300; ret2 = sum(r['place_payout'] for r in yr_recs if r['trio_hit'])
    # 三連複のみ
    inv3 = len(yr_recs)*100; ret3 = sum(r['payout_trio']*100 for r in yr_recs if r['trio_hit'])
    # 分岐0.10
    th=0.10
    inv4 = sum(200 if r['gap12']>=th else 300 for r in yr_recs)
    ret4 = sum(r['payout_st']*100 if r['gap12']>=th and r['first_correct'] else
               r['place_payout'] if r['gap12']<th else 0 for r in yr_recs if r['trio_hit'])

    print(f'  {yr}: n={len(yr_recs):,}')
    print(f'    三連単1着固定: ROI {ret1/inv1*100:.1f}%  三連複: ROI {ret3/inv3*100:.1f}%  複勝3点: ROI {ret2/inv2*100:.1f}%  分岐0.10: ROI {ret4/inv4*100:.1f}%')

print('\nDone!')
