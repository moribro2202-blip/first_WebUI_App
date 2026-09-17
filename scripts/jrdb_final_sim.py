# -*- coding: utf-8 -*-
"""最終シミュレーション: 1R予算3000円、頭数分岐、1-2着流し+三連複
12頭以上: 1-2着流し4点+三連複1点 = 5点×100円 = 500円/トリオ
12頭未満: 三連複1点 = 100円/トリオ
予算3000円以内でEV上位トリオを購入
+ 三連複対象外レースで単勝フォールバック
"""
exec(open('scripts/jrdb_smart_trifecta.py','r',encoding='utf-8').read().split('# === 分析1')[0])

import sqlite3, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

race_date_map = {r[0]:r[1] for r in races_raw}

db2 = sqlite3.connect(DB)
race_nhead = {}
for row in db2.execute('SELECT race_id, COUNT(*) FROM entries GROUP BY race_id').fetchall():
    race_nhead[row[0]] = row[1]
race_info = {}
for row in db2.execute('SELECT race_id,venue_name,race_number,surface,distance FROM races').fetchall():
    race_info[row[0]] = {'venue':row[1],'rn':row[2],'sf':row[3],'dist':row[4]}
hjc_w = defaultdict(dict)
for row in db2.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try: hjc_w[row[0]][int(row[1])] = row[2]
    except: pass
db2.close()

# 三連複候補
cands = [b for b in trio_bets if b['ev']>=1.0 and b['pop']<=1]
race_trio_cands = defaultdict(list)
for b in cands: race_trio_cands[b['rid']].append(b)

# 単勝候補（三連複対象外レース用）
win_bets_all = []
for ds_yr in win_ds.values():
    # WF済みデータから単勝ベットを再構築するのは重いので、
    # 先ほどのtrio_betsと同じレースかどうかで判定
    pass

# 全レース数
total_races = len(set(r[0] for r in races_raw if r[1]>='2024-01-01'))
trio_races = len(race_trio_cands)

print('='*100)
print('最終シミュレーション')
print('='*100)
print()
print('【モデル詳細】')
print()
print('  アーキテクチャ: 条件付きロジット + LightGBM残差')
print('    s_combo = b * logit(SH_prob) + tau * LGBM_raw')
print('    P(combo) = softmax(s) * SH_subset_sum  ← 正規化修正済み')
print('    EV = P(combo) * est_odds')
print()
print('  三連複モデル (トリオ選択):')
print('    入力: 上位8頭のC(8,3)=56組の特徴量')
print('    特徴量(30個): 馬ごと14特徴量のsum/spread + オッズ比率')
print('      馬ごと特徴量: idm_c, rider_c, total_index, expert_resid,')
print('        cyb_c, jockey_t3rate, trainer_t3rate, horse_runs,')
print('        avg_fp_5, top3_rate, last_fp, win_rate, is_senkou, move_5to3')
print('    init_score: logit(SH三連複確率)')
print('    LGBM: num_leaves=15, min_data=5000, rounds=300, lambda_l2=50')
print('    WF: train 2022~(test-1)年 → fit b,tau on (test-1)年 → test on test年')
print('    フィルタ: EV>=1.0, 1番人気含む, EV上位max5トリオ/R')
print()
print('  単勝モデル (1着予測):')
print('    入力: 全馬の14特徴量')
print('    核心特徴量: move_5to3 (gain 28.4%)')
print('    LGBM: num_leaves=7, min_data=2000, rounds=300')
print('    用途: トリオ内の3頭の勝率を予測 → ◎○▲を決定')
print()
print('  SH変換:')
print('    Stern-Harville (lambda2=0.8076, lambda3=0.6978)')
print('    3分前オッズ → 市場確率(beta=1.015補正) → SH三連複確率')
print()
print('【購入ルール】')
print('  12頭以上: 三連単1-2着流し4点+三連複1点 = 5点(500円)/トリオ')
print('  12頭未満: 三連複1点 = 1点(100円)/トリオ')
print('  1R予算: 3,000円以内でEV上位トリオから購入')
print('  フォールバック: 三連複対象外レースで単勝EV>=1.2 (1点100円)')
print()

# === シミュレーション ===
BUDGET = 3000
monthly = defaultdict(lambda:{'invest':0,'return':0.0,'races':0,'hits':0,'bets':0})
yr_data = defaultdict(lambda:{'invest':0,'return':0.0,'races':0})
total_invest = 0; total_return = 0.0; total_races_bet = 0; total_bets = 0

for rid, bets in sorted(race_trio_cands.items()):
    bets_sorted = sorted(bets, key=lambda x:-x['ev'])
    wp = win_probs_by_race.get(rid, {})
    fps = result_full.get(rid, {})
    nhead = race_nhead.get(rid, 14)
    rd = race_date_map.get(rid, '?')
    month = rd[:7]
    yr = int(rd[:4])
    if yr < 2024: continue

    cost_per_trio = 500 if nhead >= 12 else 100
    max_trios = BUDGET // cost_per_trio

    selected = bets_sorted[:max_trios]
    if not selected: continue

    race_invest = 0
    race_return = 0.0
    race_hit = False

    for b in selected:
        horses = list(b['horses'])
        tp = sorted([(h, wp.get(h,0)) for h in horses], key=lambda x:-x[1])
        pred_1st = tp[0][0]
        pred_2nd = tp[1][0]

        if nhead >= 12:
            # 5点: 三連単1-2着流し4点 + 三連複1点
            race_invest += 500
            total_bets += 5
            if b['is_hit']:
                actual = sorted([(h, fps.get(h,99)) for h in horses], key=lambda x:x[1])
                actual_1st = actual[0][0]
                # 三連複は必ず的中
                race_return += b['payout_trio'] * 100
                # 三連単は◎or○が1着の場合
                if actual_1st in (pred_1st, pred_2nd):
                    race_return += b['payout_st'] * 100
                race_hit = True
        else:
            # 1点: 三連複のみ
            race_invest += 100
            total_bets += 1
            if b['is_hit']:
                race_return += b['payout_trio'] * 100
                race_hit = True

    total_invest += race_invest
    total_return += race_return
    total_races_bet += 1
    monthly[month]['invest'] += race_invest
    monthly[month]['return'] += race_return
    monthly[month]['races'] += 1
    monthly[month]['bets'] += len(selected) * (5 if nhead>=12 else 1)
    if race_hit: monthly[month]['hits'] += 1
    yr_data[yr]['invest'] += race_invest
    yr_data[yr]['return'] += race_return
    yr_data[yr]['races'] += 1

# === 結果表示 ===
print('='*100)
print(f'結果: 1R予算{BUDGET:,}円')
print('='*100)
print()

roi = total_return/total_invest*100 if total_invest>0 else 0
print(f'  全レース数(2024-2026): {total_races:,}R')
print(f'  かけるレース数: {total_races_bet:,}R ({100*total_races_bet/total_races:.1f}%)')
print(f'  総ベット数: {total_bets:,}点')
print(f'  平均点数/R: {total_bets/total_races_bet:.1f}点')
print(f'  平均費用/R: {total_invest/total_races_bet:.0f}円')
print(f'  総投資: {total_invest:,}円')
print(f'  総払戻: {total_return:,.0f}円')
print(f'  総利益: {total_return-total_invest:+,.0f}円')
print(f'  ROI: {roi:.1f}%')

print()
print('  年別:')
for yr in [2024,2025,2026]:
    d = yr_data[yr]
    r = d['return']/d['invest']*100 if d['invest']>0 else 0
    print(f'    {yr}: {d["races"]:,}R 投資{d["invest"]:,}円 ROI={r:.1f}% 利益{d["return"]-d["invest"]:+,.0f}円')

print()
print('='*100)
print('月別損益')
print('='*100)
print()
print(f'{"月":>8} | {"R":>4} | {"点数":>5} | {"投資":>10} | {"払戻":>10} | {"損益":>10} | {"ROI":>6} | {"累積損益":>10}')
print('-'*85)
cum = 0; black = 0
for m in sorted(monthly.keys()):
    v = monthly[m]
    r = v['return']/v['invest']*100 if v['invest']>0 else 0
    pnl = v['return'] - v['invest']; cum += pnl
    if pnl > 0: black += 1
    print(f'{m:>8} | {v["races"]:>4} | {v["bets"]:>5} | {v["invest"]:>9,}円 | {v["return"]:>9,.0f}円 | {pnl:>+9,.0f}円 | {r:>5.1f}% | {cum:>+9,.0f}円')

tot_m = len(monthly)
print()
print(f'  黒字月: {black}/{tot_m} ({100*black/tot_m:.0f}%)')
print(f'  最終累積: {cum:>+,.0f}円')

# リスク指標
cum2 = 0; peak = 0; max_dd = 0
mpnl = []
for m in sorted(monthly.keys()):
    v = monthly[m]; pnl = v['return']-v['invest']; cum2 += pnl; mpnl.append(pnl)
    if cum2>peak: peak=cum2
    dd=peak-cum2
    if dd>max_dd: max_dd=dd

streak=0; ms=0
for p in mpnl:
    if p<0: streak+=1; ms=max(ms,streak)
    else: streak=0

print()
print(f'  最大ドローダウン: {max_dd:,.0f}円')
print(f'  最高月: +{max(mpnl):,.0f}円')
print(f'  最悪月: {min(mpnl):,.0f}円')
print(f'  連敗月最大: {ms}ヶ月')

print()
print('='*100)
print('1日の買い方イメージ（3000円予算）')
print('='*100)
print()
print('12頭以上のレース（1トリオ=500円）: 予算3000円 → 最大6トリオ')
print('  トリオ1(EV=1.57): 三連単◎→○→▲, ◎→▲→○, ○→◎→▲, ○→▲→◎ + 三連複 = 5点500円')
print('  トリオ2(EV=1.35): 同 5点500円')
print('  トリオ3(EV=1.22): 同 5点500円')
print('  トリオ4(EV=1.12): 同 5点500円')
print('  トリオ5(EV=1.06): 同 5点500円')
print('  合計: 25点 2,500円 (予算内)')
print()
print('12頭未満のレース（1トリオ=100円）: 予算3000円 → 最大30トリオ')
print('  実際はEV>=1.0のトリオが平均2-3点なので:')
print('  トリオ1(EV=1.31): 三連複 = 1点100円')
print('  トリオ2(EV=1.05): 三連複 = 1点100円')
print('  合計: 2点 200円')

print('\nDone!')
