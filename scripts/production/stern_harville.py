# -*- coding: utf-8 -*-
"""Stern-Harville: 不変量テスト + λフィット + 複勝キャリブレーション
Fable指示: 順列確率から複勝率を積み上げ、比率テーブルは廃止
"""
import sqlite3, math, sys, numpy as np
from collections import defaultdict
from itertools import combinations
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB)
print("Loading...", flush=True)

# レースと着順
races_raw = db.execute(
    "SELECT race_id, race_date FROM races WHERE race_date >= '2022-01-01' ORDER BY race_date"
).fetchall()

result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_full[row[0]][row[1]] = row[2]

race_horses = {}
for rid, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs:
        race_horses[rid] = sorted(hs)

ts1 = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=1 AND odds>0').fetchall():
    ts1[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]

db.close()
print("Loaded.", flush=True)


def market_prob(rid, hl):
    """市場確率（β=1.015補正）"""
    odds_src = ts1.get(rid, {})
    if len(odds_src) < len(hl) * 0.8:
        odds_src = sed.get(rid, {})
    inv = np.array([1 / odds_src.get(h, 999) for h in hl])
    s = inv.sum()
    if s == 0:
        return None
    p = inv / s
    p = p ** 1.015
    p /= p.sum()
    return p


def stern_place_wide(p, lam2, lam3):
    """Stern-Harville順列確率からplace(top3)とwideを計算
    p: 勝率ベクトル（合計1）
    lam2, lam3: Stern補正パラメータ
    Returns: place[i], wide[(a,b)]
    """
    n = len(p)
    p2 = p ** lam2
    p3 = p ** lam3
    S1 = p.sum()
    S2 = p2.sum()
    S3 = p3.sum()

    place = np.zeros(n)
    wide = defaultdict(float)
    umaren = defaultdict(float)

    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0:
            continue
        for j in range(n):
            if j == i:
                continue
            pij = (p[i] / S1) * (p2[j] / d2)
            umaren[tuple(sorted([i, j]))] += pij
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0:
                continue
            for k in range(n):
                if k in (i, j):
                    continue
                pijk = pij * (p3[k] / d3)
                place[i] += pijk
                place[j] += pijk
                place[k] += pijk
                for a, b in combinations(sorted([i, j, k]), 2):
                    wide[(a, b)] += pijk

    return place, wide, umaren


# === 1. 不変量テスト ===
print(f"\n{'='*70}")
print("=== 不変量テスト（λ2=0.9, λ3=0.8で初期テスト）===")
print(f"{'='*70}")

lam2_init, lam3_init = 0.9, 0.8
sum_place_list = []
sum_wide_list = []
sum_umaren_list = []
n_tested = 0

for rid, rd in races_raw[:500]:  # 最初の500レースでテスト
    hl = race_horses.get(rid, [])
    if len(hl) < 5 or len(hl) > 18:
        continue
    p = market_prob(rid, hl)
    if p is None:
        continue

    place, wide, umaren = stern_place_wide(p, lam2_init, lam3_init)
    sum_place_list.append(place.sum())
    sum_wide_list.append(sum(wide.values()))
    sum_umaren_list.append(sum(umaren.values()))
    n_tested += 1

print(f"  テストレース数: {n_tested}")
print(f"  Σ複勝:  mean={np.mean(sum_place_list):.6f} (期待値=3.0)")
print(f"  Σワイド: mean={np.mean(sum_wide_list):.6f} (期待値=3.0)")
print(f"  Σ馬連:  mean={np.mean(sum_umaren_list):.6f} (期待値=1.0)")
print(f"  Σ複勝 range: [{min(sum_place_list):.4f}, {max(sum_place_list):.4f}]")

if abs(np.mean(sum_place_list) - 3.0) < 0.01 and abs(np.mean(sum_wide_list) - 3.0) < 0.01:
    print("  ✅ 不変量テスト通過")
else:
    print("  ❌ 不変量テスト失敗")

# === 2. λフィット ===
print(f"\n{'='*70}")
print("=== λフィット（2022-2025でフィット）===")
print(f"{'='*70}")

# 学習データ: 1着・2着・3着が全て判明しているレース
fit_races = []
for rid, rd in races_raw:
    year = int(rd[:4])
    if year >= 2026:
        continue  # 2026はテスト
    hl = race_horses.get(rid, [])
    if len(hl) < 5 or len(hl) > 18:
        continue
    fps = result_full.get(rid, {})
    if not fps:
        continue
    # 1着・2着・3着を特定
    top3 = sorted([(fp, hn) for hn, fp in fps.items() if fp <= 3])
    if len(top3) < 3:
        continue
    win_hn = top3[0][1]
    sec_hn = top3[1][1]
    thi_hn = top3[2][1]
    if win_hn not in hl or sec_hn not in hl or thi_hn not in hl:
        continue
    p = market_prob(rid, hl)
    if p is None:
        continue
    # インデックス
    win_idx = hl.index(win_hn)
    sec_idx = hl.index(sec_hn)
    thi_idx = hl.index(thi_hn)
    fit_races.append((p, (win_idx, sec_idx, thi_idx)))

print(f"  フィットレース数: {len(fit_races)}")


def neg_ll(theta):
    l2, l3 = theta
    if l2 <= 0 or l2 > 2 or l3 <= 0 or l3 > 2:
        return 1e10
    nll = 0
    for p, (i, j, k) in fit_races:
        p2 = p ** l2
        p3 = p ** l3
        S1 = p.sum()
        term1 = p[i] / S1
        d2 = p2.sum() - p2[i]
        if d2 <= 0:
            return 1e10
        term2 = p2[j] / d2
        d3 = p3.sum() - p3[i] - p3[j]
        if d3 <= 0:
            return 1e10
        term3 = p3[k] / d3
        if term1 <= 0 or term2 <= 0 or term3 <= 0:
            return 1e10
        nll -= (math.log(term1) + math.log(term2) + math.log(term3))
    return nll / len(fit_races)


res = minimize(neg_ll, x0=[0.9, 0.8], method='Nelder-Mead',
               options={'maxiter': 2000, 'xatol': 1e-5, 'fatol': 1e-8})
lam2_fit, lam3_fit = res.x
print(f"  λ2 = {lam2_fit:.4f}")
print(f"  λ3 = {lam3_fit:.4f}")
print(f"  NLL = {res.fun:.6f}")

# === 3. 不変量テスト（フィット済みλ）===
print(f"\n{'='*70}")
print(f"=== 不変量テスト（λ2={lam2_fit:.4f}, λ3={lam3_fit:.4f}）===")
print(f"{'='*70}")

sum_place2 = []
sum_wide2 = []
for rid, rd in races_raw[:500]:
    hl = race_horses.get(rid, [])
    if len(hl) < 5 or len(hl) > 18:
        continue
    p = market_prob(rid, hl)
    if p is None:
        continue
    place, wide, _ = stern_place_wide(p, lam2_fit, lam3_fit)
    sum_place2.append(place.sum())
    sum_wide2.append(sum(wide.values()))

print(f"  Σ複勝:  mean={np.mean(sum_place2):.6f} (期待値=3.0)")
print(f"  Σワイド: mean={np.mean(sum_wide2):.6f} (期待値=3.0)")

# === 4. 複勝キャリブレーション（順列版、2026年テスト）===
print(f"\n{'='*70}")
print(f"=== 複勝キャリブレーション（Stern-Harville順列版、2024-2026）===")
print(f"{'='*70}")

all_place_data = []
for rid, rd in races_raw:
    year = int(rd[:4])
    if year < 2024:
        continue
    hl = race_horses.get(rid, [])
    if len(hl) < 5 or len(hl) > 18:
        continue
    fps = result_full.get(rid, {})
    if not fps:
        continue
    p = market_prob(rid, hl)
    if p is None:
        continue

    odds_src = ts1.get(rid, sed.get(rid, {}))
    place, wide, _ = stern_place_wide(p, lam2_fit, lam3_fit)

    for i, h in enumerate(hl):
        o = odds_src.get(h, 0)
        fp = fps.get(h, 99)
        all_place_data.append({
            'odds': o,
            'place_pred': float(place[i]),
            'win_pred': float(p[i]),
            'is_place': int(fp <= 3),
            'is_win': int(fp == 1),
        })

print(f"  データ: {len(all_place_data):,}")
print()
print(f"  {'オッズ帯':>10} {'n':>7} {'予測複勝':>8} {'実複勝':>7} {'比':>5} {'予測勝率':>8} {'実勝率':>7}")
print(f"  {'-'*65}")

bands = [(1, 2), (2, 3), (3, 5), (5, 8), (8, 12), (12, 20), (20, 35), (35, 60), (60, 100), (100, 500)]
for lo, hi in bands:
    sub = [d for d in all_place_data if lo <= d['odds'] < hi]
    if not sub:
        continue
    n = len(sub)
    pred_p = np.mean([d['place_pred'] for d in sub])
    act_p = np.mean([d['is_place'] for d in sub])
    pred_w = np.mean([d['win_pred'] for d in sub])
    act_w = np.mean([d['is_win'] for d in sub])
    ratio = act_p / pred_p if pred_p > 0 else 0
    print(f"  {lo:>3}-{hi:<4}x {n:>7} {pred_p:>7.4f} {act_p:>6.4f} {ratio:>4.2f} {pred_w:>7.4f} {act_w:>6.4f}")

print("\nDone!")
