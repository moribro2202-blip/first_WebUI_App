# -*- coding: utf-8 -*-
"""買い目拡張の分析: 1トリオあたりの点数と買い方の最適化"""
exec(open('scripts/jrdb_smart_trifecta.py','r',encoding='utf-8').read().split('# === 分析1')[0])

import sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

db2 = sqlite3.connect(DB)
race_nhead = {}
for row in db2.execute('SELECT race_id, COUNT(*) FROM entries GROUP BY race_id').fetchall():
    race_nhead[row[0]] = row[1]
db2.close()

cands = [b for b in trio_bets if b['ev']>=1.0 and b['pop']<=1]
race_cands = defaultdict(list)
for b in cands: race_cands[b['rid']].append(b)

# 各トリオの着順パターン
records = []
for rid, bets in race_cands.items():
    bets_sorted = sorted(bets, key=lambda x:-x['ev'])[:5]
    wp = win_probs_by_race.get(rid, {})
    fps = result_full.get(rid, {})
    nhead = race_nhead.get(rid, 14)
    for b in bets_sorted:
        horses = list(b['horses'])
        tp = sorted([(h, wp.get(h,0)) for h in horses], key=lambda x:-x[1])
        pattern = 'miss'
        if b['is_hit']:
            actual = sorted([(h, fps.get(h,99)) for h in horses], key=lambda x:x[1])
            if actual[0][0]==tp[0][0]: pattern = '1st_correct'
            elif actual[0][0]==tp[1][0]: pattern = '2nd_wins'
            else: pattern = '3rd_wins'
        records.append({
            'rid':rid, 'nhead':nhead, 'trio_hit':b['is_hit'], 'pattern':pattern,
            'payout_st':b['payout_st'], 'payout_trio':b['payout_trio'],
            'p1':tp[0][1], 'p2':tp[1][1], 'p3':tp[2][1],
        })

hits = [r for r in records if r['trio_hit']]
print('='*80)
print('三連複的中時: 1着は誰だった？')
print('='*80)
n_hit = len(hits)
n_1st = sum(1 for r in hits if r['pattern']=='1st_correct')
n_2nd = sum(1 for r in hits if r['pattern']=='2nd_wins')
n_3rd = sum(1 for r in hits if r['pattern']=='3rd_wins')
print(f'  的中数: {n_hit}')
print(f'  ◎(モデル1位)が1着: {n_1st} ({100*n_1st/n_hit:.1f}%)')
print(f'  ○(モデル2位)が1着: {n_2nd} ({100*n_2nd/n_hit:.1f}%)')
print(f'  ▲(モデル3位)が1着: {n_3rd} ({100*n_3rd/n_hit:.1f}%)')

print()
print('='*80)
print('買い方別ROI比較（全レコード）')
print('='*80)
print()

# 買い方の定義
def calc(name, cost_fn, ret_fn):
    inv = sum(cost_fn(r) for r in records)
    ret = sum(ret_fn(r) for r in records)
    roi = ret/inv*100 if inv>0 else 0
    n_r = len(set(r['rid'] for r in records))
    avg = inv/n_r
    print(f'  {name:>40} | cost={avg:>5.0f}円/R | ROI={roi:>5.1f}% | profit={ret-inv:>+9,.0f}円')

print('  三連単の買い方:')
calc('1着固定2点(◎→○▲, ◎→▲○)',
     lambda r: 200,
     lambda r: r['payout_st']*100 if r['trio_hit'] and r['pattern']=='1st_correct' else 0)

calc('1-2着流し4点(◎→○▲ + ○→◎▲ + ○→▲◎ + ◎→▲○)',
     lambda r: 400,
     lambda r: r['payout_st']*100 if r['trio_hit'] and r['pattern'] in ('1st_correct','2nd_wins') else 0)

calc('ボックス6点(全順列)',
     lambda r: 600,
     lambda r: r['payout_st']*100 if r['trio_hit'] else 0)

print()
print('  三連複:')
calc('三連複1点',
     lambda r: 100,
     lambda r: r['payout_trio']*100 if r['trio_hit'] else 0)

print()
print('  組み合わせ:')
calc('1着固定 + 三連複 (3点300円)',
     lambda r: 300,
     lambda r: (r['payout_st']*100 if r['pattern']=='1st_correct' else 0) + (r['payout_trio']*100 if r['trio_hit'] else 0))

calc('1-2着流し + 三連複 (5点500円)',
     lambda r: 500,
     lambda r: (r['payout_st']*100 if r['pattern'] in ('1st_correct','2nd_wins') else 0) + (r['payout_trio']*100 if r['trio_hit'] else 0))

calc('ボックス + 三連複 (7点700円)',
     lambda r: 700,
     lambda r: (r['payout_st']*100 if r['trio_hit'] else 0) + (r['payout_trio']*100 if r['trio_hit'] else 0))

print()
print('='*80)
print('頭数分岐: 12頭以上→三連単、12頭未満→三連複')
print('='*80)
print()

def calc_split(name, cost_fn_st, ret_fn_st, cost_fn_tr, ret_fn_tr):
    inv = 0; ret = 0
    for r in records:
        if r['nhead'] >= 12:
            inv += cost_fn_st(r); ret += ret_fn_st(r)
        else:
            inv += cost_fn_tr(r); ret += ret_fn_tr(r)
    roi = ret/inv*100 if inv>0 else 0
    n_r = len(set(r['rid'] for r in records))
    avg = inv/n_r
    print(f'  {name:>40} | cost={avg:>5.0f}円/R | ROI={roi:>5.1f}% | profit={ret-inv:>+9,.0f}円')

calc_split('12+: 1着固定2点 / <12: 三連複1点',
    lambda r: 200, lambda r: r['payout_st']*100 if r['trio_hit'] and r['pattern']=='1st_correct' else 0,
    lambda r: 100, lambda r: r['payout_trio']*100 if r['trio_hit'] else 0)

calc_split('12+: 1-2着流し4点 / <12: 三連複1点',
    lambda r: 400, lambda r: r['payout_st']*100 if r['trio_hit'] and r['pattern'] in ('1st_correct','2nd_wins') else 0,
    lambda r: 100, lambda r: r['payout_trio']*100 if r['trio_hit'] else 0)

calc_split('12+: 1着固定+三連複(300円) / <12: 三連複1点',
    lambda r: 300, lambda r: (r['payout_st']*100 if r['pattern']=='1st_correct' else 0)+(r['payout_trio']*100 if r['trio_hit'] else 0),
    lambda r: 100, lambda r: r['payout_trio']*100 if r['trio_hit'] else 0)

calc_split('12+: 1-2着流し+三連複(500円) / <12: 三連複1点',
    lambda r: 500, lambda r: (r['payout_st']*100 if r['pattern'] in ('1st_correct','2nd_wins') else 0)+(r['payout_trio']*100 if r['trio_hit'] else 0),
    lambda r: 100, lambda r: r['payout_trio']*100 if r['trio_hit'] else 0)

calc_split('12+: box+三連複(700円) / <12: 三連複1点',
    lambda r: 700, lambda r: (r['payout_st']*100 if r['trio_hit'] else 0)+(r['payout_trio']*100 if r['trio_hit'] else 0),
    lambda r: 100, lambda r: r['payout_trio']*100 if r['trio_hit'] else 0)

print()
print('='*80)
print('具体例: 1レースの買い目（12頭以上、3トリオの場合）')
print('='*80)
print()
print('  1着固定2点の場合:')
print('    トリオ1: ◎7→3→5, ◎7→5→3 (200円)')
print('    トリオ2: ◎7→2→9, ◎7→9→2 (200円)')
print('    トリオ3: ◎7→1→3, ◎7→3→1 (200円)')
print('    合計: 6点 600円')
print()
print('  1-2着流し4点の場合:')
print('    トリオ1: ◎7→3→5, ◎7→5→3, ○3→7→5, ○3→5→7 (400円)')
print('    トリオ2: 同様 (400円)')
print('    トリオ3: 同様 (400円)')
print('    合計: 12点 1,200円')
print()
print('  1着固定+三連複(保険)の場合:')
print('    トリオ1: 三連単◎7→3→5, ◎7→5→3 + 三連複3-5-7 (300円)')
print('    トリオ2: 同様 (300円)')
print('    トリオ3: 同様 (300円)')
print('    合計: 9点 900円')

print('\nDone!')
