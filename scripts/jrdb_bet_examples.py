# -*- coding: utf-8 -*-
"""三連単1着固定の具体的なかけ方の例"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

# jrdb_smart_trifecta.py の前半を再利用してデータ構築
exec(open('scripts/jrdb_smart_trifecta.py','r',encoding='utf-8').read().split('# === 分析1')[0])

race_date_map = {r[0]:r[1] for r in races_raw}
cands = [b for b in trio_bets if b['ev']>=1.0 and b['pop']<=1]
race_cands = defaultdict(list)
for b in cands: race_cands[b['rid']].append(b)

db2 = sqlite3.connect(DB)
race_info = {}
for row in db2.execute('SELECT race_id,venue_name,race_number,surface,distance,race_name FROM races').fetchall():
    race_info[row[0]] = {'venue':row[1],'rn':row[2],'sf':row[3],'dist':row[4],'name':row[5] or ''}
db2.close()

# 1日分の全体像
print('='*100)
print('三連単1着固定 — 具体的なかけ方（2026-08-02の1日分）')
print('='*100)
print()
print('【ルール】')
print('  1. 三連複モデルが「この3頭が3着以内」と判定（EV>=1.0, 1番人気含む）')
print('  2. 単勝モデルで3頭の中の1着を予測')
print('  3. 予測1着を頭に固定し、残り2頭の順列2点を各100円で購入')
print('  4. 1トリオ = 三連単2点 = 200円')
print()

target_date = '2026-08-02'
day_invest = 0
day_return = 0
day_races = 0
day_bets = 0

for rid in sorted(race_cands.keys()):
    rd = race_date_map.get(rid, '')
    if rd != target_date: continue
    ri = race_info.get(rid, {})
    bets = sorted(race_cands[rid], key=lambda x: -x['ev'])[:5]
    if not bets: continue
    day_races += 1
    wp = win_probs_by_race.get(rid, {})
    fps = result_full.get(rid, {})

    # レースの実際の着順
    all_hl = race_horses.get(rid, [])
    actual_top3 = sorted([(h, fps.get(h, 99)) for h in all_hl if fps.get(h, 99) <= 3], key=lambda x: x[1])
    actual_str = ' > '.join([str(h) + '番' for h, _ in actual_top3])

    venue_rn = ri.get('venue', '') + str(ri.get('rn', '')) + 'R'
    race_label = ri.get('sf', '') + str(ri.get('dist', '')) + 'm ' + ri.get('name', '')

    print(f'  {venue_rn} {race_label}')
    print(f'  結果: {actual_str}')

    race_inv = 0
    race_ret = 0
    for b in bets:
        horses = list(b['horses'])
        tp = sorted([(h, wp.get(h, 0)) for h in horses], key=lambda x: -x[1])
        pred_1st = tp[0][0]
        pred_prob = tp[0][1]
        h2, h3 = tp[1][0], tp[2][0]

        buy1 = f'{pred_1st}-{h2}-{h3}'
        buy2 = f'{pred_1st}-{h3}-{h2}'

        mark = 'x'
        payout = 0
        if b['is_hit']:
            top3_actual = sorted([(h, fps.get(h, 99)) for h in horses], key=lambda x: x[1])
            if top3_actual[0][0] == pred_1st:
                mark = 'HIT'
                payout = b['payout_st'] * 100
                race_ret += payout
            else:
                mark = '3頭正解/1着外れ'

        race_inv += 200
        trio_str = '-'.join(str(h) for h in sorted(horses))
        print(f'    {trio_str} EV={b["ev"]:.2f} | 1着予測:{pred_1st}番({pred_prob:.0%}) | 買:{buy1}, {buy2} 各100円 | {mark}', end='')
        if payout > 0:
            print(f' {b["payout_st"]:.1f}倍 = {payout:,.0f}円')
        else:
            print()

    day_invest += race_inv
    day_return += race_ret
    day_bets += len(bets) * 2
    pnl = race_ret - race_inv
    pnl_str = f'+{pnl:,.0f}' if pnl >= 0 else f'{pnl:,.0f}'
    print(f'  → {len(bets)}組{len(bets)*2}点 投資{race_inv}円 払戻{race_ret:,.0f}円 ({pnl_str}円)')
    print()

print('─' * 60)
print(f'  {target_date} 合計: {day_races}R {day_bets}点')
print(f'  投資: {day_invest:,}円')
print(f'  払戻: {day_return:,.0f}円')
print(f'  損益: {day_return - day_invest:+,.0f}円')
print(f'  ROI:  {day_return / day_invest * 100:.1f}%')

# もう1日（大当たりの日）
print()
print()
print('='*100)
print('三連単1着固定 — 大当たりの日（2026-07-27）')
print('='*100)
print()

target_date = '2026-07-27'
day_invest = 0
day_return = 0
day_races = 0

for rid in sorted(race_cands.keys()):
    rd = race_date_map.get(rid, '')
    if rd != target_date: continue
    ri = race_info.get(rid, {})
    bets = sorted(race_cands[rid], key=lambda x: -x['ev'])[:5]
    if not bets: continue
    day_races += 1
    wp = win_probs_by_race.get(rid, {})
    fps = result_full.get(rid, {})
    all_hl = race_horses.get(rid, [])
    actual_top3 = sorted([(h, fps.get(h, 99)) for h in all_hl if fps.get(h, 99) <= 3], key=lambda x: x[1])
    actual_str = ' > '.join([str(h) + '番' for h, _ in actual_top3])
    venue_rn = ri.get('venue', '') + str(ri.get('rn', '')) + 'R'

    race_inv = 0
    race_ret = 0
    line_parts = []
    for b in bets:
        horses = list(b['horses'])
        tp = sorted([(h, wp.get(h, 0)) for h in horses], key=lambda x: -x[1])
        pred_1st = tp[0][0]
        h2, h3 = tp[1][0], tp[2][0]
        mark = 'x'
        payout = 0
        if b['is_hit']:
            top3_a = sorted([(h, fps.get(h, 99)) for h in horses], key=lambda x: x[1])
            if top3_a[0][0] == pred_1st:
                mark = f'HIT {b["payout_st"]:.0f}倍'
                payout = b['payout_st'] * 100
                race_ret += payout
            else:
                mark = '1着外れ'
        trio_str = '-'.join(str(h) for h in sorted(horses))
        line_parts.append(f'{trio_str}({mark})')
        race_inv += 200

    day_invest += race_inv
    day_return += race_ret
    pnl = race_ret - race_inv
    pnl_str = f'+{pnl:,.0f}' if pnl >= 0 else f'{pnl:,.0f}'
    hit_mark = ' ★' if race_ret > 0 else ''
    print(f'  {venue_rn} {len(bets)}組 投資{race_inv}円 → {pnl_str}円{hit_mark}  {" | ".join(line_parts)}')

print()
print(f'  合計: {day_races}R 投資{day_invest:,}円 払戻{day_return:,.0f}円 損益{day_return-day_invest:+,.0f}円 ROI {day_return/day_invest*100:.1f}%')

print()
print()
print('='*100)
print('まとめ: アプリでの表示イメージ')
print('='*100)
print('''
┌──────────────────────────────────────────┐
│ 中京5R ダート1200m 2歳未勝利             │
│ 予算: 200円 (1組 × 三連単2点)            │
│──────────────────────────────────────────│
│ ◎ 3番 (1着予測: 勝率42%)                │
│ ○ 7番                                    │
│ ▲ 11番                                   │
│──────────────────────────────────────────│
│ 買い目:                                   │
│   三連単 3→7→11  100円                    │
│   三連単 3→11→7  100円                    │
│──────────────────────────────────────────│
│ EV: 1.35  推定配当: 約180倍               │
└──────────────────────────────────────────┘
''')
