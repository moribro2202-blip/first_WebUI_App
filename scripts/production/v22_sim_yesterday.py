# -*- coding: utf-8 -*-
"""v22シミュレーション: 昨日のレースで券種自動選択をテスト"""
import sys, os, sqlite3, math, json, numpy as np, lightgbm as lgb
from collections import defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB = os.path.join(BASE, 'data', 'jrdb.db')
MODEL_DIR = os.path.join(BASE, 'data', 'models')

with open(os.path.join(MODEL_DIR, 'prod_config.json'), 'r', encoding='utf-8') as f:
    win_config = json.load(f)
win_model = lgb.Booster(model_file=os.path.join(MODEL_DIR, win_config['model_file']))
with open(os.path.join(MODEL_DIR, 'prod_trio_config_v22.json'), 'r', encoding='utf-8') as f:
    trio_config = json.load(f)
trio_model = lgb.Booster(model_file=os.path.join(MODEL_DIR, trio_config['model_file']))
print('Models loaded')

from realtime_bet import build_features, predict_with_move, predict_trio
from bet_selector import select_best_bets, BET_TYPE_JP

db = sqlite3.connect(DB, timeout=30)
races = db.execute("SELECT race_id, venue_name, race_number, surface, distance, start_time, race_name, venue_code, track_condition, grade FROM races WHERE race_date='2026-09-13' ORDER BY start_time").fetchall()
ts3 = defaultdict(dict); ts5 = defaultdict(dict)
# まずrealtime_oddsから（当日記録されたもの優先）
for row in db.execute("SELECT race_id,horse_number,odds,snapshot_label FROM realtime_odds WHERE race_date='2026-09-13'").fetchall():
    if row[3] == '3min': ts3[row[0]][row[1]] = row[2]
    elif row[3] == '5min': ts5[row[0]][row[1]] = row[2]
# ts_win_oddsで補完
for row in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=3 AND odds>0').fetchall():
    if row[0] not in ts3 or row[1] not in ts3[row[0]]:
        ts3[row[0]][row[1]] = row[2]
for row in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=5 AND odds>0').fetchall():
    if row[0] not in ts5 or row[1] not in ts5[row[0]]:
        ts5[row[0]][row[1]] = row[2]
result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_full[row[0]][row[1]] = row[2]
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
db.close()

print(f'Races: {len(races)}')
total_invest = 0; total_payout = 0; race_results = []

for rid, vn, rn, sf, dist, st, rname, vc, tc, grade in races:
    o3 = ts3.get(rid, {}); o5 = ts5.get(rid, {})
    if len(o3) < 5: continue
    race = {'race_id':rid,'venue_name':vn,'race_number':rn,'surface':sf,'distance':dist,
            'start_time':st,'race_name':rname,'venue_code':vc,
            'track_condition':tc or '良','grade':grade or '一般','deadline':st}
    try:
        with open(os.path.join(MODEL_DIR, win_config.get('stats_file','')), 'r', encoding='utf-8') as f:
            stats = json.load(f)
    except:
        stats = None
    try:
        race_data = build_features(race, o3, win_config, stats)
    except Exception as e:
        print(f'  {vn}{rn}R build_features error: {e}')
        continue
    if race_data is None:
        print(f'  {vn}{rn}R race_data is None (o3={len(o3)}頭)')
        continue

    predictions = predict_with_move(race_data, o5, o3, win_model, win_config)
    horses = race_data['horses']
    win_probs = np.array([0.0]*len(horses))
    for p in predictions:
        idx = horses.index(p['horse_number'])
        win_probs[idx] = p['model_prob']

    selection = select_best_bets(
        horses=horses, win_probs=win_probs,
        odds_3min=o3, odds_5min=o5,
        trio_model=trio_model, trio_config=trio_config, race_data=race_data,
        ev_threshold=1.2, race_budget=1000)

    best_type = selection['best_type']
    best_bets = selection['bets']
    all_cands = selection['all_candidates']
    fps = result_full.get(rid, {})

    bt_jp = BET_TYPE_JP.get(best_type, 'なし') if best_type else 'なし'
    cands_str = ' '.join(f'{BET_TYPE_JP.get(k,k)}={v}' for k,v in all_cands.items() if v>0)

    if best_bets:
        n_bets = len(best_bets)
        per_bet = best_bets[0].get('amount', 100)
        invest = n_bets * per_bet
        total_invest += invest
        payout = 0
        for bet in best_bets:
            combo = bet['combo']
            if best_type == 'win':
                hn = int(combo)
                if fps.get(hn) == 1:
                    hjc_o = hjc_all.get(rid,{}).get('win_hjc',{}).get(str(hn),0)
                    payout += hjc_o * per_bet
            elif best_type == 'sanrenpuku':
                top3 = sorted([(h,fp) for h,fp in fps.items() if fp<=3], key=lambda x:x[1])
                if len(top3) >= 3:
                    winner = '-'.join(str(x[0]) for x in sorted(top3[:3], key=lambda x:x[0]))
                    if combo == winner:
                        hjc_o = hjc_all.get(rid,{}).get('sanrenpuku_hjc',{}).get(combo,0)
                        payout += hjc_o * per_bet
            elif best_type == 'umaren':
                top2 = sorted([(h,fp) for h,fp in fps.items() if fp<=2], key=lambda x:x[1])
                if len(top2) >= 2:
                    winner = '-'.join(str(x[0]) for x in sorted(top2[:2], key=lambda x:x[0]))
                    if combo == winner:
                        hjc_o = hjc_all.get(rid,{}).get('umaren_hjc',{}).get(combo,0)
                        payout += hjc_o * per_bet
        total_payout += payout
        hit = '★的中' if payout > 0 else ''
        print(f'{vn}{rn:>2}R {bt_jp:>4} {n_bets}点×{per_bet}円={invest:>5}円 → {payout:>6,.0f}円 {hit:>4} [{cands_str}] top1={selection["top1_prob"]:.0%}')
        race_results.append({'type':best_type,'invest':invest,'payout':payout,'hit':payout>0})
    else:
        print(f'{vn}{rn:>2}R  なし                                [{cands_str}] top1={selection["top1_prob"]:.0%}')

print(f'\n{"="*60}')
print(f'合計: 投資={total_invest:,}円 払戻={total_payout:,.0f}円')
if total_invest > 0:
    print(f'回収率: {total_payout/total_invest*100:.1f}%  PnL: {total_payout-total_invest:+,.0f}円')
# 券種別集計
by_type = defaultdict(lambda: {'n':0,'invest':0,'payout':0,'hits':0})
for r in race_results:
    t = by_type[r['type']]
    t['n'] += 1; t['invest'] += r['invest']; t['payout'] += r['payout']
    if r['hit']: t['hits'] += 1
print(f'\n券種別:')
for bt, d in sorted(by_type.items()):
    rec = d['payout']/d['invest']*100 if d['invest']>0 else 0
    print(f'  {BET_TYPE_JP.get(bt,bt)}: {d["n"]}R 投資{d["invest"]:,}円 払戻{d["payout"]:,.0f}円 回収率{rec:.1f}% 的中{d["hits"]}R')
