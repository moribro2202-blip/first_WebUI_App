# -*- coding: utf-8 -*-
"""複勝率/勝率の比率テーブル生成
Harvilleの「複勝≈3×勝率」の代わりに、実データに基づく比率を使用
"""
import json, numpy as np

# 2024-2026の実データから算出した比率
# 勝率 → 複勝率/勝率
PLACE_RATIO_TABLE = {
    # (win_prob_lo, win_prob_hi): place_to_win_ratio
    (0.40, 1.00): 1.68,  # 1-2x帯
    (0.25, 0.40): 2.08,  # 2-3x帯
    (0.15, 0.25): 2.57,  # 3-5x帯
    (0.07, 0.15): 3.16,  # 5-8x帯
    (0.04, 0.07): 3.62,  # 8-12x帯
    (0.02, 0.04): 4.58,  # 12-20x帯
    (0.01, 0.02): 4.80,  # 20-35x帯
    (0.005, 0.01): 6.34, # 35-60x帯
    (0.002, 0.005): 6.25,# 60-100x帯
    (0.0, 0.002): 8.89,  # 100x+帯
}

def win_to_place_prob(win_prob):
    """勝率から複勝率（3着以内確率）を推定"""
    for (lo, hi), ratio in sorted(PLACE_RATIO_TABLE.items(), key=lambda x: -x[0][0]):
        if win_prob >= lo:
            return min(1.0, win_prob * ratio)
    return min(1.0, win_prob * 8.89)

def win_to_top2_prob(win_prob):
    """勝率から連対率（2着以内確率）を推定
    連対率/勝率もオッズ帯で異なる。実データ近似:
    top2_ratio ≈ place_ratio * 0.65（大雑把だが0次近似）
    """
    place_p = win_to_place_prob(win_prob)
    # 連対率は複勝率の約65%（実データから）
    return min(1.0, place_p * 0.65)

# テスト
if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print("=== 勝率 → 複勝率・連対率 変換テーブル ===")
    print(f"  {'勝率':>7} {'複勝率':>7} {'複/勝':>6} {'連対率':>7}")
    for wp in [0.50, 0.33, 0.20, 0.12, 0.08, 0.05, 0.03, 0.015, 0.008, 0.003]:
        pp = win_to_place_prob(wp)
        tp = win_to_top2_prob(wp)
        print(f"  {wp:>6.3f} {pp:>6.3f} {pp/wp:>5.1f}x {tp:>6.3f}")

    # JSON出力
    print("\n=== prod_config用 ===")
    table = []
    for (lo, hi), ratio in sorted(PLACE_RATIO_TABLE.items()):
        table.append({"win_prob_lo": lo, "win_prob_hi": hi, "place_ratio": ratio})
    print(json.dumps({"place_ratio_table": table}, indent=2))
