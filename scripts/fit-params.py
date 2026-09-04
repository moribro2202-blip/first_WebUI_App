"""
scaleFactor と alpha の最尤推定スクリプト

入力: 過去レースの [確定単勝オッズ, 勝ち馬] のリスト
※ AIのaiScoreは過去データにはないため、alpha=0（市場のみ）を
   ベースラインとして、市場確率のβ補正のみフィットする。
   scaleFactorはaiScoreが蓄積されてから改めてフィットする。

推定パラメータ:
  - alpha: ブレンド係数（0=市場のみ、1=モデルのみ）
    → 現時点ではaiScoreがないので alpha=0.2 を暫定値として維持
  - scaleFactor: softmax温度 → 暫定値0.15を維持

このスクリプトでは、市場確率の精度（ベースライン）を確認する。
"""

import sqlite3
import math
from collections import defaultdict

DB_PATH = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'

db = sqlite3.connect(DB_PATH)

# Get all results with odds
rows = db.execute('''
    SELECT r.race_id, r.horse_number, r.finish_position, r.win_odds
    FROM results r
    WHERE r.win_odds IS NOT NULL AND r.win_odds > 0
      AND r.finish_position IS NOT NULL
''').fetchall()

# Group by race
races = defaultdict(list)
for race_id, horse_num, finish_pos, odds in rows:
    races[race_id].append((horse_num, finish_pos, odds))

# Build race data: (market_probs, winner_index)
race_data = []
for race_id, horses in races.items():
    if len(horses) < 2:
        continue
    inverses = [1.0 / h[2] for h in horses if h[2] > 0]
    total_inv = sum(inverses)
    if total_inv == 0:
        continue
    market_probs = [(1.0 / h[2]) / total_inv for h in horses]
    winner_idx = None
    for i, (_, fp, _) in enumerate(horses):
        if fp == 1:
            winner_idx = i
            break
    if winner_idx is not None:
        race_data.append((market_probs, winner_idx))

print(f'Total races: {len(race_data)}')
print()

# --- Beta fitting (already done, verify) ---

def log_likelihood_beta(beta, data):
    ll = 0.0
    for probs, winner in data:
        powered = [p ** beta for p in probs]
        total = sum(powered)
        if total == 0: continue
        pw = powered[winner] / total
        if pw > 0: ll += math.log(pw)
    return ll

print('=== Beta verification ===')
for beta in [0.9, 1.0, 1.03, 1.05, 1.1]:
    ll = log_likelihood_beta(beta, race_data)
    print(f'  beta={beta:.2f}  LL={ll:.2f}')

# --- Alpha simulation ---
# Without aiScore, we simulate what happens when model = market + noise
# alpha=0 means pure market, which is the baseline

print()
print('=== Alpha analysis (market-only baseline) ===')

# Log-likelihood with alpha=0 (pure market, beta-corrected)
ll_market = log_likelihood_beta(1.03, race_data)
print(f'  alpha=0 (market only, beta=1.03): LL = {ll_market:.2f}')
print(f'  alpha=0 (market only, beta=1.00): LL = {log_likelihood_beta(1.0, race_data):.2f}')

# Per-race average
avg_ll = ll_market / len(race_data)
print(f'  Per-race avg LL: {avg_ll:.4f}')
print(f'  Per-race avg prob of winner: {math.exp(avg_ll):.4f} ({math.exp(avg_ll)*100:.1f}%)')

print()
print('=== Recommended config ===')
print('  scaleFactor: 0.15 (暫定値、aiScore蓄積後に再フィット)')
print('  alpha: 0.2 (暫定値、モデル20% + 市場80%)')
print('  marketBeta: 1.03 (データから推定済み)')
print()
print('NOTE: scaleFactorとalphaの正確なフィットには')
print('過去レースでのaiScore予測値が必要です。')
print('予想を蓄積してから再度このスクリプトを実行してください。')

db.close()
