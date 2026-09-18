# -*- coding: utf-8 -*-
"""v12: 補正済み複勝率テーブルで複勝・ワイドのEV帯別シミュレーション
calibration_win_place.pyの結果を使用
"""
import sqlite3, math, sys, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

# 複勝率/勝率の比率テーブル（実データ）
PLACE_RATIO = [
    (0.40, 1.00, 1.68),
    (0.25, 0.40, 2.08),
    (0.15, 0.25, 2.57),
    (0.07, 0.15, 3.16),
    (0.04, 0.07, 3.62),
    (0.02, 0.04, 4.58),
    (0.01, 0.02, 4.80),
    (0.005, 0.01, 6.34),
    (0.002, 0.005, 6.25),
    (0.0, 0.002, 8.89),
]

def win_to_place(wp):
    for lo, hi, r in PLACE_RATIO:
        if wp >= lo:
            return min(0.99, wp * r)
    return min(0.99, wp * 8.89)

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB)
print("Loading...", flush=True)

# 簡略ロード（calibration_win_place.pyと同じ）
races_raw = db.execute("SELECT race_id,race_date FROM races WHERE race_date >= '2022-01-01' ORDER BY race_date").fetchall()

result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_full[row[0]][row[1]] = row[2]

ts1 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds

hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]

race_horses = {}
for rid, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs:
        race_horses[rid] = sorted(hs)

db.close()
print("Loaded.", flush=True)

# モデル確率の代わりに市場確率を使う（モデルWFは重いので）
# 市場確率ベースで「正しい複勝率テーブル」の効果を検証
print("Computing...", flush=True)

all_bets = []
for rid, rd in races_raw:
    year = int(rd[:4])
    if year < 2024:
        continue  # 2024-2026のみ
    hl = race_horses.get(rid, [])
    if len(hl) < 5:
        continue
    fps = result_full.get(rid, {})
    if not fps:
        continue

    odds_mkt = ts1.get(rid, {})
    if len(odds_mkt) < len(hl) * 0.8:
        continue

    inv = np.array([1 / odds_mkt.get(h, 999) for h in hl])
    s = inv.sum()
    if s == 0:
        continue
    mp = inv / s
    mp = mp ** 1.015
    mp /= mp.sum()

    # 複勝オッズ: 3着以内の馬にのみ存在
    hjc_place_dict = hjc_all.get(rid, {}).get('place_hjc', {})

    # 複勝オッズの平均（全馬のEV計算に使う）
    # 各馬の複勝オッズがない場合は推定: 1/place_p * 0.8（控除率20%）
    for i, h in enumerate(hl):
        win_p = mp[i]
        place_p = win_to_place(win_p)
        o_win = odds_mkt.get(h, 0)
        fp = fps.get(h, 99)

        # 単勝
        hjc_w = hjc_all.get(rid, {}).get('win_hjc', {}).get(str(h), 0)
        # 複勝（的中時のみHJCに値がある）
        hjc_p = hjc_place_dict.get(str(h), 0)
        is_place = int(fp <= 3)

        # 複勝EV = place_prob × 推定複勝オッズ
        # 推定複勝オッズ = 1/place_p * 0.8（控除率前提）
        est_place_odds = (1.0 / place_p * 0.8) if place_p > 0.01 else 0
        ev_place = place_p * est_place_odds

        all_bets.append({
            'year': year, 'rid': rid, 'hn': h,
            'win_p': win_p, 'place_p': place_p,
            'odds_win': o_win, 'fp': fp,
            'is_win': int(fp == 1), 'is_place': is_place,
            'hjc_win': hjc_w, 'hjc_place': hjc_p,
            'ev_win': win_p * o_win,
            'ev_place': ev_place,
            'est_place_odds': est_place_odds,
        })

print(f"Total: {len(all_bets):,}")

# === 単勝 EV帯別 ===
print(f"\n{'='*80}")
print("単勝 EV帯別（市場確率ベース、2024-2026）")
print(f"{'='*80}")
print(f"  {'EV帯':>10} {'n':>7} {'勝数':>5} {'投資':>10} {'HJC払戻':>10} {'回収率':>7}")
for lo, hi in [(0.5, 0.8), (0.8, 0.9), (0.9, 1.0), (1.0, 1.1), (1.1, 1.2), (1.2, 1.5), (1.5, 5.0)]:
    sub = [b for b in all_bets if lo <= b['ev_win'] < hi and b['odds_win'] > 0]
    if not sub: continue
    n = len(sub); wins = sum(b['is_win'] for b in sub)
    inv = n * 100; pay = sum(b['hjc_win'] * 100 for b in sub if b['is_win'] and b['hjc_win'] > 0)
    rec = pay / inv * 100 if inv > 0 else 0
    print(f"  {lo:.1f}-{hi:.1f} {n:>7} {wins:>5} {inv:>9,}円 {pay:>9,.0f}円 {rec:>6.1f}%")

# === 複勝 EV帯別（補正済み）===
print(f"\n{'='*80}")
print("複勝 EV帯別（補正済み複勝率テーブル、2024-2026）")
print(f"{'='*80}")
print(f"  {'EV帯':>10} {'n':>7} {'的中':>5} {'投資':>10} {'HJC払戻':>10} {'回収率':>7} {'予測P':>7} {'実P':>6}")
for lo, hi in [(0.5, 0.8), (0.8, 0.9), (0.9, 1.0), (1.0, 1.1), (1.1, 1.2), (1.2, 1.5), (1.5, 5.0)]:
    sub = [b for b in all_bets if lo <= b['ev_place'] < hi and b['ev_place'] > 0]
    if not sub: continue
    n = len(sub); hits = sum(b['is_place'] for b in sub)
    inv = n * 100; pay = sum(b['hjc_place'] * 100 for b in sub if b['is_place'])
    rec = pay / inv * 100 if inv > 0 else 0
    avg_pred = np.mean([b['place_p'] for b in sub])
    avg_act = hits / n
    print(f"  {lo:.1f}-{hi:.1f} {n:>7} {hits:>5} {inv:>9,}円 {pay:>9,.0f}円 {rec:>6.1f}% {avg_pred:>6.3f} {avg_act:>5.3f}")

# === 複勝 キャリブレーション ===
print(f"\n{'='*80}")
print("複勝キャリブレーション: 予測複勝率 vs 実複勝率（オッズ帯別）")
print(f"{'='*80}")
print(f"  {'オッズ帯':>10} {'n':>7} {'予測複勝':>8} {'実複勝':>7} {'比':>5} {'HJC回収率':>8}")
bands = [(1, 2), (2, 3), (3, 5), (5, 8), (8, 12), (12, 20), (20, 35), (35, 60), (60, 100), (100, 500)]
for lo_o, hi_o in bands:
    sub = [b for b in all_bets if lo_o <= b['odds_win'] < hi_o]
    if not sub: continue
    n = len(sub)
    avg_pred = np.mean([b['place_p'] for b in sub])
    avg_act = np.mean([b['is_place'] for b in sub])
    ratio = avg_act / avg_pred if avg_pred > 0 else 0
    inv = n * 100; pay = sum(b['hjc_place'] * 100 for b in sub if b['is_place'])
    rec = pay / inv * 100 if inv > 0 else 0
    print(f"  {lo_o:>3}-{hi_o:<4}x {n:>7} {avg_pred:>7.4f} {avg_act:>6.4f} {ratio:>4.2f} {rec:>7.1f}%")

# === ワイド（モデル上位2頭）EV帯別 ===
print(f"\n{'='*80}")
print("ワイド（市場確率上位2頭）EV帯別")
print(f"{'='*80}")

# レースごとに上位2頭のワイド
wide_bets = []
for rid, rd in races_raw:
    year = int(rd[:4])
    if year < 2024: continue
    hl = race_horses.get(rid, [])
    if len(hl) < 5: continue
    fps = result_full.get(rid, {})
    odds_mkt = ts1.get(rid, {})
    if len(odds_mkt) < len(hl) * 0.8: continue
    inv = np.array([1 / odds_mkt.get(h, 999) for h in hl])
    s = inv.sum()
    if s == 0: continue
    mp = inv / s; mp = mp ** 1.015; mp /= mp.sum()

    sorted_idx = np.argsort(mp)[::-1]
    h1 = hl[sorted_idx[0]]; h2 = hl[sorted_idx[1]]
    p1 = mp[sorted_idx[0]]; p2 = mp[sorted_idx[1]]
    place_p1 = win_to_place(p1); place_p2 = win_to_place(p2)
    # ワイド確率 ≈ P(両方top3) - 独立近似
    wide_p = place_p1 * place_p2
    combo_key = '-'.join(str(x) for x in sorted([h1, h2]))
    hjc_wide = hjc_all.get(rid, {}).get('wide_hjc', {}).get(combo_key, 0)
    if hjc_wide <= 0: continue
    ev_wide = wide_p * hjc_wide
    fp1 = fps.get(h1, 99); fp2 = fps.get(h2, 99)
    is_hit = int(fp1 <= 3 and fp2 <= 3)
    wide_bets.append({
        'year': year, 'ev': ev_wide, 'hjc': hjc_wide,
        'is_hit': is_hit, 'wide_p': wide_p,
        'p1': p1, 'p2': p2, 'h1': h1, 'h2': h2,
    })

print(f"  {'EV帯':>10} {'n':>7} {'的中':>5} {'投資':>10} {'HJC払戻':>10} {'回収率':>7} {'予測P':>7} {'実P':>6}")
for lo, hi in [(0.0, 0.5), (0.5, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 1.5), (1.5, 3.0), (3.0, 50.0)]:
    sub = [b for b in wide_bets if lo <= b['ev'] < hi]
    if not sub: continue
    n = len(sub); hits = sum(b['is_hit'] for b in sub)
    inv = n * 100; pay = sum(b['hjc'] * 100 for b in sub if b['is_hit'])
    rec = pay / inv * 100 if inv > 0 else 0
    avg_pred = np.mean([b['wide_p'] for b in sub])
    avg_act = hits / n
    print(f"  {lo:.1f}-{hi:.1f} {n:>7} {hits:>5} {inv:>9,}円 {pay:>9,.0f}円 {rec:>6.1f}% {avg_pred:>6.3f} {avg_act:>5.3f}")

print("\nDone!")
