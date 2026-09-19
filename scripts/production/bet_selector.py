# -*- coding: utf-8 -*-
"""券種自動選択エンジン v23

1レースの予測結果から、最適な券種と買い目を選択する。

v23 戦略:
  1. トリオモデル(or SH)で三連複候補を生成（EV>=1.0、1番人気含む）
  2. 単勝モデルの勝率で3頭内の着順予測（◎=1着率最高、○=2番目）
  3. 頭数による券種切替:
     - 12頭以上: 三連単1-2着流し(4点) + 三連複(1点) = 5点×100円 = 500円/トリオ
       三連単: ◎→○→▲, ◎→▲→○, ○→◎→▲, ○→▲→◎
       三連複: 1組（保険）
     - 12頭未満: 三連複のみ = 1点×100円 = 100円/トリオ
  4. EV順にトリオを選択、race_budget内で収まるだけ
  5. フォールバック: トリオ候補がなければ単勝（EV>=1.2, 2-40倍）

注意: 推定オッズは確定オッズと乖離する（Fable警告）。
      ペーパー記録で実測してから実弾に移行すること。
"""
import math, numpy as np
from collections import defaultdict
from itertools import combinations, permutations


# 控除率
TAKEOUT = {
    'win': 0.20,
    'umaren': 0.225,
    'umatan': 0.225,
    'sanrenpuku': 0.25,
    'sanrentan': 0.2725,
}

LAM2, LAM3 = 0.8076, 0.6978

FEAT_KEYS_PAIR = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
                   'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
                   'top3_rate','last_fp','win_rate','is_senkou','move_5to3']


def sh_all_probs(p):
    """単勝確率から全券種のSH確率を算出"""
    n = len(p)
    p2 = p**LAM2; p3 = p**LAM3
    S1 = p.sum(); S2 = p2.sum(); S3 = p3.sum()
    umaren = defaultdict(float)
    umatan = {}
    trio = defaultdict(float)
    trifecta = {}
    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0: continue
        for j in range(n):
            if j == i: continue
            pij = (p[i]/S1) * (p2[j]/d2)
            umaren[tuple(sorted([i,j]))] += pij
            umatan[(i,j)] = pij
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk = pij * (p3[k]/d3)
                trio[tuple(sorted([i,j,k]))] += pijk
                trifecta[(i,j,k)] = pijk
    return umaren, umatan, trio, trifecta


def apply_odds_calibration(est_odds, cal_table):
    """推定オッズに補正テーブルを適用"""
    if not cal_table:
        return est_odds
    for entry in cal_table:
        lo, hi, ratio = entry[0], entry[1], entry[2]
        if lo <= est_odds < hi:
            return est_odds * ratio
    return est_odds


def select_best_bets(horses, win_probs, odds_3min, odds_5min,
                     trio_model=None, trio_config=None, race_data=None,
                     exotic_models=None, exotic_config=None,
                     ev_threshold=1.2, ev_threshold_trio=1.0, race_budget=1000):
    """1レースで最適な券種と買い目を選択 (v23)

    Args:
        horses: [馬番, ...]
        win_probs: np.array 各馬のモデル勝率
        odds_3min: {馬番: 3分前オッズ}
        odds_5min: {馬番: 5分前オッズ}
        trio_model: トリオ残差LightGBMモデル（Noneなら三連複はSHのみ）
        trio_config: トリオモデル設定
        race_data: 単勝モデルのrace_data（トリオ特徴量構築用）
        exotic_models: 連系モデル辞書（未使用、互換用）
        exotic_config: 連系モデル設定（未使用、互換用）
        ev_threshold: EV閾値（単勝フォールバック用、デフォルト1.2）
        race_budget: 1レースの予算

    Returns:
        {
            'best_type': 'sanrenpuku' | 'sanrentan' | 'win' | 'portfolio' | None,
            'bets': [{'combo', 'ev', 'model_prob', 'est_odds', 'bet_type', 'amount'}, ...],
            'reason': str,
            'all_candidates': {券種: 候補数},
            'top1_prob': float,
            'top1_hn': int,
        }
    """
    n = len(horses)
    if n < 5:
        return {'best_type': None, 'bets': [], 'reason': '頭数不足',
                'all_candidates': {}, 'top1_prob': 0.0, 'top1_hn': 0}

    # SH確率
    umaren_p, umatan_p, trio_p, trifecta_p = sh_all_probs(win_probs)

    # 上位8頭（勝率順）
    sorted_idx = np.argsort(win_probs)[::-1]
    top8_idx = sorted_idx[:min(8, n)]
    top8_hns = [horses[i] for i in top8_idx]

    # top1の情報
    top1_idx = sorted_idx[0]
    top1_hn = horses[top1_idx]
    top1_prob = win_probs[top1_idx]

    # 馬ごと特徴量辞書（将来の残差モデル用）
    feats_h = {}
    if race_data and 'X' in race_data and 'feature_names' in race_data:
        win_fnames = race_data['feature_names']
        for i, h in enumerate(horses):
            f = {}
            for k in FEAT_KEYS_PAIR:
                if k in win_fnames:
                    f[k] = float(race_data['X'][i, win_fnames.index(k)])
                else:
                    f[k] = 0
            o5 = odds_5min.get(h, 0); o3 = odds_3min.get(h, 0)
            f['move_5to3'] = (o5-o3)/o5 if o5>0 and o3>0 else 0
            f['win_odds_3min'] = o3
            feats_h[h] = f

    # 全券種の候補を生成
    candidates = {}

    # --- 単勝 ---
    win_cands = []
    for i in range(n):
        h = horses[i]
        o = odds_3min.get(h, 0)
        if o <= 0 or not (2 <= o <= 40): continue
        ev = win_probs[i] * o
        if ev >= ev_threshold:
            win_cands.append({
                'combo': str(h), 'ev': float(ev), 'model_prob': float(win_probs[i]),
                'est_odds': float(o), 'bet_type': 'win',
            })
    win_cands.sort(key=lambda x: -x['ev'])
    candidates['win'] = win_cands

    # --- 馬連（上位8頭のC(8,2)=28組）--- 将来用、選択対象外
    um_cands = []
    um_cal = exotic_config.get('odds_calibration',{}).get('umaren',[]) if exotic_config else []
    for a, b in combinations(top8_idx, 2):
        key = tuple(sorted([a, b]))
        sh_p = umaren_p.get(key, 0)
        if sh_p <= 0: continue
        est_odds = (1/sh_p) * (1-TAKEOUT['umaren'])
        cal_odds = apply_odds_calibration(est_odds, um_cal)
        ev = sh_p * cal_odds
        if ev >= ev_threshold:
            h1, h2 = horses[a], horses[b]
            um_cands.append({
                'combo': '-'.join(str(x) for x in sorted([h1, h2])),
                'ev': float(ev), 'model_prob': float(sh_p),
                'est_odds': float(cal_odds), 'bet_type': 'umaren',
            })
    um_cands.sort(key=lambda x: -x['ev'])
    candidates['umaren'] = um_cands

    # --- 三連複（トリオ残差モデル or SHのみ、1番人気含む、EV>=閾値）---
    TRIO_EV_THRESHOLD = ev_threshold_trio
    trio_cands = []
    trio_all = []  # 閾値以下も含む全候補（ログ表示用）
    tr_model = exotic_models.get('trio') if exotic_models else trio_model
    tr_info = exotic_config.get('models',{}).get('trio',{}) if exotic_config else (trio_config or {})
    tr_cal = exotic_config.get('odds_calibration',{}).get('sanrenpuku',[]) if exotic_config else []

    if tr_model and tr_info and race_data:
        from realtime_bet import predict_trio
        tr_cfg = {**exotic_config, **tr_info} if exotic_config else trio_config
        trio_preds = predict_trio(race_data, odds_5min, odds_3min, tr_model, tr_cfg)
        for tp in trio_preds:
            # 1番人気含むもののみ
            combo_hns = [int(x) for x in tp['combo'].split('-')]
            if top1_hn not in combo_hns:
                continue
            cal_odds = apply_odds_calibration(tp['est_odds'], tr_cal)
            tp['ev'] = tp['model_prob'] * cal_odds
            tp['est_odds'] = cal_odds
            trio_all.append(tp)
            if tp['ev'] >= TRIO_EV_THRESHOLD:
                trio_cands.append(tp)
    else:
        # SHのみ: 上位8頭のC(8,3)で1番人気含む
        # softmax正規化の修正: SH確率は全組の合計が1ではなく、
        # subsetの合計がSH全体の合計に対する割合になるため、
        # subsetのsoftmax後に全体のSH合計を掛けて絶対確率に戻す
        sh_subset_sum = 0.0
        sh_subset_items = []
        for a, b, c in combinations(top8_idx, 3):
            key = tuple(sorted([a, b, c]))
            sh_p = trio_p.get(key, 0)
            if sh_p <= 0: continue
            # 1番人気含むもののみ
            if top1_idx not in (a, b, c):
                continue
            sh_subset_sum += sh_p
            sh_subset_items.append((a, b, c, key, sh_p))

        for a, b, c, key, sh_p in sh_subset_items:
            est_odds = (1/sh_p) * (1-TAKEOUT['sanrenpuku'])
            cal_odds = apply_odds_calibration(est_odds, tr_cal)
            ev = sh_p * cal_odds
            h1, h2, h3 = horses[a], horses[b], horses[c]
            entry = {
                'combo': '-'.join(str(x) for x in sorted([h1, h2, h3])),
                'ev': float(ev), 'model_prob': float(sh_p),
                'est_odds': float(cal_odds), 'bet_type': 'sanrenpuku',
            }
            trio_all.append(entry)
            if ev >= TRIO_EV_THRESHOLD:
                trio_cands.append(entry)
    trio_cands.sort(key=lambda x: -x['ev'])
    trio_all.sort(key=lambda x: -x['ev'])
    candidates['sanrenpuku'] = trio_cands

    # === v23 券種選択ロジック ===
    # 1. トリオ候補をEV順に選択、race_budget内で収まるだけ
    # 2. 頭数で券種切替: 12頭以上=三連単流し+三連複、12頭未満=三連複のみ
    # 3. フォールバック: トリオ候補なし → 単勝

    best_type = None
    best_bets = []
    best_reason = 'EV>=閾値の組合せなし'

    # 馬番→インデックスの逆引き
    hn_to_idx = {h: i for i, h in enumerate(horses)}

    if trio_cands:
        # 頭数による1トリオあたりのコスト・上限
        cost_per_trio = 500 if n >= 12 else 100  # 5点 or 1点
        max_trios = 3  # 投票時間制約+ROI最適化: 全頭数でmax3

        # EV順にrace_budget内かつmax_trios以内で選択
        selected_trios = []
        remaining_budget = race_budget
        for tc in trio_cands:
            if len(selected_trios) >= max_trios:
                break
            if remaining_budget < cost_per_trio:
                break
            selected_trios.append(tc)
            remaining_budget -= cost_per_trio

        if selected_trios:
            # 総点数を計算して1点あたりの金額を決定（100円単位切り下げ）
            pts_per_trio = 5 if n >= 12 else 1
            total_pts = len(selected_trios) * pts_per_trio
            per_bet = max(100, (race_budget // total_pts // 100) * 100)

            bets = []
            for tc in selected_trios:
                combo_hns = [int(x) for x in tc['combo'].split('-')]
                # 3頭の勝率でソート: ◎=最高、○=2番目、▲=3番目
                trio_with_prob = []
                for hn in combo_hns:
                    idx = hn_to_idx.get(hn)
                    wp = win_probs[idx] if idx is not None else 0.0
                    trio_with_prob.append((hn, wp))
                trio_with_prob.sort(key=lambda x: -x[1])
                honmei_hn = trio_with_prob[0][0]   # ◎
                taikou_hn = trio_with_prob[1][0]   # ○
                anaume_hn = trio_with_prob[2][0]    # ▲

                if n >= 12:
                    # 三連単 1-2着流し: ◎or○が1着、残りが2着、▲が3着
                    # 4 permutations
                    sanrentan_combos = [
                        (honmei_hn, taikou_hn, anaume_hn),  # ◎→○→▲
                        (honmei_hn, anaume_hn, taikou_hn),  # ◎→▲→○
                        (taikou_hn, honmei_hn, anaume_hn),  # ○→◎→▲
                        (taikou_hn, anaume_hn, honmei_hn),  # ○→▲→◎
                    ]
                    for first, second, third in sanrentan_combos:
                        i1 = hn_to_idx.get(first)
                        i2 = hn_to_idx.get(second)
                        i3 = hn_to_idx.get(third)
                        st_key = (i1, i2, i3) if i1 is not None and i2 is not None and i3 is not None else None
                        st_prob = trifecta_p.get(st_key, 0) if st_key else 0
                        st_est_odds = (1/st_prob) * (1-TAKEOUT['sanrentan']) if st_prob > 0 else 0
                        bets.append({
                            'combo': f'{first}-{second}-{third}',
                            'ev': float(st_prob * st_est_odds) if st_prob > 0 else 0.0,
                            'model_prob': float(st_prob),
                            'est_odds': float(st_est_odds),
                            'bet_type': 'sanrentan',
                            'amount': per_bet,
                            'trio_origin': tc['combo'],
                        })

                    # 三連複 保険1点
                    bets.append({
                        'combo': tc['combo'],
                        'ev': float(tc['ev']),
                        'model_prob': float(tc['model_prob']),
                        'est_odds': float(tc['est_odds']),
                        'bet_type': 'sanrenpuku',
                        'amount': per_bet,
                        'trio_origin': tc['combo'],
                    })
                else:
                    # 12頭未満: 三連複のみ
                    bets.append({
                        'combo': tc['combo'],
                        'ev': float(tc['ev']),
                        'model_prob': float(tc['model_prob']),
                        'est_odds': float(tc['est_odds']),
                        'bet_type': 'sanrenpuku',
                        'amount': per_bet,
                        'trio_origin': tc['combo'],
                    })

            best_type = 'portfolio' if n >= 12 else 'sanrenpuku'
            best_bets = bets
            total_cost = sum(b['amount'] for b in bets)
            n_trios = len(selected_trios)
            avg_ev = np.mean([tc['ev'] for tc in selected_trios])
            best_reason = (f'{n_trios}トリオ '
                          f'{"三連単+三連複" if n >= 12 else "三連複のみ"} '
                          f'{len(bets)}点 {total_cost}円 '
                          f'avg_EV={avg_ev:.2f} nhead={n}')

    # フォールバック: トリオ候補なし → 単勝
    if not best_bets and win_cands:
        best_type = 'win'
        best_bets = win_cands
        n_bets = len(best_bets)
        per_bet = max(100, (race_budget // n_bets // 100) * 100)
        for b in best_bets:
            b['amount'] = per_bet
        avg_ev = np.mean([c['ev'] for c in best_bets])
        best_reason = (f'単勝{n_bets}点 avg_EV={avg_ev:.2f} '
                      f'top1確率={top1_prob:.1%}')

    return {
        'best_type': best_type,
        'bets': best_bets,
        'reason': best_reason,
        'all_candidates': {bt: len(c) for bt, c in candidates.items()},
        'trio_top': trio_all[:5],  # 三連複EV上位5（閾値以下も含む）
        'top1_prob': float(top1_prob),
        'top1_hn': int(top1_hn),
    }


# 券種名の日本語マッピング
BET_TYPE_JP = {
    'win': '単勝',
    'umaren': '馬連',
    'sanrenpuku': '三連複',
    'sanrentan': '三連単',
    'portfolio': '三連単+三連複',
}
