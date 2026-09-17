# -*- coding: utf-8 -*-
"""三連複/三連単の合理的切り替え条件探索
条件候補:
  - gap12: 1位と2位の勝率差 → 大きい=1着が明確→三連単有利
  - gap23: 2位と3位の勝率差 → 大きい=2-3着が固い→三連単有利
  - p1: 1着予測の勝率自体 → 高い=1着自信→三連単
  - spread: 1位-3位の勝率差 → 大きい=序列明確→三連単
  - ratio12: p1/p2 → 高い=1着が抜けている→三連単
  - EV: 三連複のEV → 高い=確信度→三連単も自信
  - nhead: 頭数 → 少ない=荒れにくい→三連単有利？
"""
exec(open('scripts/jrdb_smart_trifecta.py','r',encoding='utf-8').read().split('# === 分析1')[0])

import sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

race_date_map = {r[0]:r[1] for r in races_raw}

import sqlite3
db2 = sqlite3.connect(DB)
race_nhead = {}
for row in db2.execute('SELECT race_id, COUNT(*) FROM entries GROUP BY race_id').fetchall():
    race_nhead[row[0]] = row[1]
db2.close()

cands = [b for b in trio_bets if b['ev']>=1.0 and b['pop']<=1]
race_cands = defaultdict(list)
for b in cands: race_cands[b['rid']].append(b)

# 全レコードに条件変数を付与
records = []
for rid, bets in race_cands.items():
    bets_sorted = sorted(bets, key=lambda x:-x['ev'])[:5]
    wp = win_probs_by_race.get(rid, {})
    fps = result_full.get(rid, {})
    nhead = race_nhead.get(rid, 14)

    for b in bets_sorted:
        horses = list(b['horses'])
        tp = sorted([(h, wp.get(h, 0)) for h in horses], key=lambda x: -x[1])
        p1, p2, p3 = tp[0][1], tp[1][1], tp[2][1]
        pred_1st = tp[0][0]

        gap12 = p1 - p2
        gap23 = p2 - p3
        spread = p1 - p3
        ratio12 = p1 / p2 if p2 > 0 else 99

        trio_hit = b['is_hit']
        first_correct = False
        if trio_hit:
            actual_top3 = sorted([(h, fps.get(h, 99)) for h in horses], key=lambda x: x[1])
            first_correct = (actual_top3[0][0] == pred_1st)

        records.append({
            'rid': rid, 'year': b['year'], 'ev': b['ev'],
            'p1': p1, 'p2': p2, 'p3': p3,
            'gap12': gap12, 'gap23': gap23, 'spread': spread, 'ratio12': ratio12,
            'nhead': nhead,
            'trio_hit': trio_hit, 'first_correct': first_correct,
            'payout_st': b['payout_st'], 'payout_trio': b['payout_trio'],
        })

print(f'Total records: {len(records):,}')

# === 各条件変数で「三連単が三連複より有利な帯」を探す ===
import numpy as np

def analyze_condition(name, values, records, thresholds):
    """閾値以上→三連単、未満→三連複 のROIを計算"""
    print(f'\n  --- {name} ---')
    print(f'  {"閾値":>8} | {"三連単(>=)":>25} | {"三連複(<)":>25} | {"合計":>20} | {"単独比":>8}')
    print('  ' + '-'*100)

    best_roi = 0; best_th = None; best_profit = 0
    for th in thresholds:
        # 三連単帯(>=th): 200円/トリオ
        st_sub = [r for r in records if values[records.index(r)] >= th]
        inv_st = len(st_sub) * 200
        ret_st = sum(r['payout_st']*100 for r in st_sub if r['trio_hit'] and r['first_correct'])
        roi_st = ret_st/inv_st*100 if inv_st>0 else 0

        # 三連複帯(<th): 100円/トリオ
        tr_sub = [r for r in records if values[records.index(r)] < th]
        inv_tr = len(tr_sub) * 100
        ret_tr = sum(r['payout_trio']*100 for r in tr_sub if r['trio_hit'])
        roi_tr = ret_tr/inv_tr*100 if inv_tr>0 else 0

        # 合計
        total_inv = inv_st + inv_tr
        total_ret = ret_st + ret_tr
        total_roi = total_ret/total_inv*100 if total_inv>0 else 0
        total_profit = total_ret - total_inv

        # 全部三連単(126.2%)との比較
        vs_all_st = total_roi - 126.2

        if total_roi > best_roi:
            best_roi = total_roi; best_th = th; best_profit = total_profit

        n_st = len(st_sub); n_tr = len(tr_sub)
        print(f'  {th:>8.3f} | n={n_st:>5,} roi={roi_st:>5.1f}% | n={n_tr:>5,} roi={roi_tr:>5.1f}% | roi={total_roi:>5.1f}% +{total_profit:>+8,.0f} | {vs_all_st:>+5.1f}pt')

    if best_th is not None:
        print(f'  BEST: {name}>={best_th:.3f} → roi={best_roi:.1f}%')
    return best_th, best_roi

# 条件変数の閾値候補
gap12_vals = [r['gap12'] for r in records]
gap23_vals = [r['gap23'] for r in records]
spread_vals = [r['spread'] for r in records]
ratio12_vals = [r['ratio12'] for r in records]
p1_vals = [r['p1'] for r in records]
nhead_vals = [r['nhead'] for r in records]
ev_vals = [r['ev'] for r in records]

print('\n' + '='*100)
print('条件探索: 三連単(>=閾値) vs 三連複(<閾値)')
print('全部三連単のROI: 126.2% (ベースライン)')
print('='*100)

results = []

th, roi = analyze_condition('gap12(1位-2位差)', gap12_vals, records,
    [0.01, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30])
results.append(('gap12', th, roi))

th, roi = analyze_condition('gap23(2位-3位差)', gap23_vals, records,
    [0.01, 0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20])
results.append(('gap23', th, roi))

th, roi = analyze_condition('spread(1位-3位差)', spread_vals, records,
    [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40])
results.append(('spread', th, roi))

th, roi = analyze_condition('ratio12(p1/p2)', ratio12_vals, records,
    [1.1, 1.2, 1.3, 1.5, 1.7, 2.0, 2.5, 3.0])
results.append(('ratio12', th, roi))

th, roi = analyze_condition('p1(1着勝率)', p1_vals, records,
    [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50])
results.append(('p1', th, roi))

th, roi = analyze_condition('nhead(頭数)', nhead_vals, records,
    [8, 10, 12, 14, 16])
results.append(('nhead', th, roi))

th, roi = analyze_condition('ev(三連複EV)', ev_vals, records,
    [1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5])
results.append(('ev', th, roi))

# === 複合条件 ===
print('\n' + '='*100)
print('複合条件探索')
print('='*100)

# 有望な組み合わせ
print(f'\n  {"条件":>40} | {"n_st":>6} {"n_tr":>6} | {"roi_st":>6} {"roi_tr":>6} | {"合計ROI":>7} {"利益":>10} | {"vs全st":>6}')
print('  ' + '-'*105)

combos = []
for gap12_th in [0.05, 0.08, 0.10, 0.15]:
    for p1_th in [0.25, 0.30, 0.35, 0.40]:
        # 条件: gap12>=th AND p1>=th → 三連単、それ以外→三連複
        st_sub = [r for r in records if r['gap12']>=gap12_th and r['p1']>=p1_th]
        tr_sub = [r for r in records if not (r['gap12']>=gap12_th and r['p1']>=p1_th)]

        inv_st = len(st_sub)*200; ret_st = sum(r['payout_st']*100 for r in st_sub if r['trio_hit'] and r['first_correct'])
        inv_tr = len(tr_sub)*100; ret_tr = sum(r['payout_trio']*100 for r in tr_sub if r['trio_hit'])
        roi_st = ret_st/inv_st*100 if inv_st>0 else 0
        roi_tr = ret_tr/inv_tr*100 if inv_tr>0 else 0
        total_inv = inv_st+inv_tr; total_ret = ret_st+ret_tr
        total_roi = total_ret/total_inv*100 if total_inv>0 else 0
        vs = total_roi - 126.2
        label = f'gap12>={gap12_th:.2f} AND p1>={p1_th:.2f}'
        combos.append((label, len(st_sub), len(tr_sub), roi_st, roi_tr, total_roi, total_ret-total_inv, vs))

# ratio12 + gap23
for r12_th in [1.3, 1.5, 2.0]:
    for g23_th in [0.03, 0.05, 0.08]:
        st_sub = [r for r in records if r['ratio12']>=r12_th and r['gap23']>=g23_th]
        tr_sub = [r for r in records if not (r['ratio12']>=r12_th and r['gap23']>=g23_th)]
        inv_st = len(st_sub)*200; ret_st = sum(r['payout_st']*100 for r in st_sub if r['trio_hit'] and r['first_correct'])
        inv_tr = len(tr_sub)*100; ret_tr = sum(r['payout_trio']*100 for r in tr_sub if r['trio_hit'])
        roi_st = ret_st/inv_st*100 if inv_st>0 else 0
        roi_tr = ret_tr/inv_tr*100 if inv_tr>0 else 0
        total_inv = inv_st+inv_tr; total_ret = ret_st+ret_tr
        total_roi = total_ret/total_inv*100 if total_inv>0 else 0
        vs = total_roi - 126.2
        label = f'ratio12>={r12_th:.1f} AND gap23>={g23_th:.2f}'
        combos.append((label, len(st_sub), len(tr_sub), roi_st, roi_tr, total_roi, total_ret-total_inv, vs))

# spread(小=団子→三連複) + p1(大=1着自信→三連単)
for sp_th in [0.15, 0.20, 0.25]:
    for p1_th in [0.30, 0.35, 0.40]:
        # spread>=th → 差がある → 三連単
        # spread<th BUT p1>=p1_th → 団子だが1着は自信 → 三連単
        # それ以外 → 三連複
        st_sub = [r for r in records if r['spread']>=sp_th or r['p1']>=p1_th]
        tr_sub = [r for r in records if r['spread']<sp_th and r['p1']<p1_th]
        inv_st = len(st_sub)*200; ret_st = sum(r['payout_st']*100 for r in st_sub if r['trio_hit'] and r['first_correct'])
        inv_tr = len(tr_sub)*100; ret_tr = sum(r['payout_trio']*100 for r in tr_sub if r['trio_hit'])
        roi_st = ret_st/inv_st*100 if inv_st>0 else 0
        roi_tr = ret_tr/inv_tr*100 if inv_tr>0 else 0
        total_inv = inv_st+inv_tr; total_ret = ret_st+ret_tr
        total_roi = total_ret/total_inv*100 if total_inv>0 else 0
        vs = total_roi - 126.2
        label = f'spread>={sp_th:.2f} OR p1>={p1_th:.2f}'
        combos.append((label, len(st_sub), len(tr_sub), roi_st, roi_tr, total_roi, total_ret-total_inv, vs))

combos.sort(key=lambda x: -x[5])
for label, n_st, n_tr, roi_st, roi_tr, total_roi, profit, vs in combos[:20]:
    print(f'  {label:>40} | {n_st:>6,} {n_tr:>6,} | {roi_st:>5.1f}% {roi_tr:>5.1f}% | {total_roi:>6.1f}% {profit:>+9,.0f} | {vs:>+5.1f}pt')

# === 年別安定性チェック（上位3設定） ===
print('\n' + '='*100)
print('年別安定性チェック（上位設定）')
print('='*100)

top_combos = combos[:5]
for label, *_ in top_combos:
    print(f'\n  {label}:')
    for yr in [2024, 2025, 2026]:
        yr_recs = [r for r in records if r['year']==yr]
        # 条件をパース...面倒なので直接計算
        # 上位1位の条件を手動で
        pass

# 直接計算
print('\n  全部三連単（ベースライン）:')
for yr in [2024,2025,2026]:
    yr_r = [r for r in records if r['year']==yr]
    inv=len(yr_r)*200; ret=sum(r['payout_st']*100 for r in yr_r if r['trio_hit'] and r['first_correct'])
    print(f'    {yr}: roi={ret/inv*100:.1f}%')

# 最良条件の年別
best_label, best_n_st, best_n_tr, *_ = combos[0]
print(f'\n  {best_label}:')
# パースして再計算
# 上位の条件がどれか表示で確認してから手動で

# 汎用: 上位3つを年別で
for rank, (label, n_st, n_tr, roi_st, roi_tr, total_roi, profit, vs) in enumerate(combos[:3]):
    print(f'\n  #{rank+1} {label} (全体ROI={total_roi:.1f}%):')
    # labelから条件を解析して年別計算...
    # 簡易版: gap12+p1の条件だけ
    if 'gap12' in label and 'p1' in label:
        parts = label.split(' AND ')
        g_th = float(parts[0].split('>=')[1])
        p_th = float(parts[1].split('>=')[1])
        for yr in [2024,2025,2026]:
            yr_r = [r for r in records if r['year']==yr]
            st_sub = [r for r in yr_r if r['gap12']>=g_th and r['p1']>=p_th]
            tr_sub = [r for r in yr_r if not (r['gap12']>=g_th and r['p1']>=p_th)]
            inv=len(st_sub)*200+len(tr_sub)*100
            ret=sum(r['payout_st']*100 for r in st_sub if r['trio_hit'] and r['first_correct'])+sum(r['payout_trio']*100 for r in tr_sub if r['trio_hit'])
            roi=ret/inv*100 if inv>0 else 0
            print(f'    {yr}: st={len(st_sub):,} tr={len(tr_sub):,} roi={roi:.1f}%')

print('\nDone!')
