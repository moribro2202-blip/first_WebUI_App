# -*- coding: utf-8 -*-
"""券種自動選択エンジン
1レースの予測結果から、最適な券種と買い目を選択する。

選択ロジック:
  1. 全券種のEVを計算
  2. レースの条件（1着率、複勝率）で場合分け
  3. 1レース予算内で最も期待利益が高い券種を選択

券種:
  - 単勝: モデル勝率 × 3分前オッズ
  - 馬連: SH確率 × 推定オッズ（トリオ残差モデルなし）
  - 馬単: SH順列確率 × 推定オッズ（1着固定時）
  - 三連複: トリオ残差モデル確率 × 推定オッズ
  - 三連単: SH順列確率 × 推定オッズ（1着固定流し）

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
                     ev_threshold=1.2, race_budget=1000):
    """1レースで最適な券種と買い目を選択

    Args:
        horses: [馬番, ...]
        win_probs: np.array 各馬のモデル勝率
        odds_3min: {馬番: 3分前オッズ}
        odds_5min: {馬番: 5分前オッズ}
        trio_model: トリオ残差LightGBMモデル（Noneなら三連複はSHのみ）
        trio_config: トリオモデル設定
        race_data: 単勝モデルのrace_data（トリオ特徴量構築用）
        ev_threshold: EV閾値
        race_budget: 1レースの予算

    Returns:
        {
            'best_type': 'win' | 'umaren' | 'sanrenpuku' | 'sanrentan',
            'bets': [{'combo', 'ev', 'model_prob', 'est_odds', 'bet_type', 'amount'}, ...],
            'reason': str,
            'all_candidates': {券種: [ベットリスト]},  # 全券種の候補（ログ用）
        }
    """
    n = len(horses)
    if n < 5:
        return {'best_type': None, 'bets': [], 'reason': '頭数不足', 'all_candidates': {}}

    # SH確率
    umaren_p, umatan_p, trio_p, trifecta_p = sh_all_probs(win_probs)

    # 上位8頭（勝率順）
    sorted_idx = np.argsort(win_probs)[::-1]
    top8_idx = sorted_idx[:min(8, n)]
    top8_hns = [horses[i] for i in top8_idx]

    # top1の情報
    top1_idx = sorted_idx[0]
    top1_hn = horses[top1_idx]
    top1_prob = win_probs[top1_idx]  # 1着率

    # 馬ごと特徴量辞書（馬連/三連単の残差モデル用）
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

    # --- 馬連（上位8頭のC(8,2)=28組）---
    um_cands = []
    # 馬連残差モデルがあれば使用
    um_model = exotic_models.get('umaren') if exotic_models else None
    um_info = exotic_config.get('models',{}).get('umaren',{}) if exotic_config else {}
    um_cal = exotic_config.get('odds_calibration',{}).get('umaren',[]) if exotic_config else []

    if um_model and um_info:
        um_fnames = um_info['feature_names']
        um_b = um_info['b']; um_tau = um_info['tau']
        um_X = []; um_init = []; um_meta_local = []; um_est_odds_list = []
        for a, b in combinations(top8_idx, 2):
            key = tuple(sorted([a, b]))
            sh_p = umaren_p.get(key, 0)
            if sh_p <= 0: continue
            h1, h2 = horses[a], horses[b]
            pf = {}
            for k in FEAT_KEYS_PAIR:
                v1 = feats_h.get(h1,{}).get(k,0); v2 = feats_h.get(h2,{}).get(k,0)
                pf[f'{k}_sum'] = v1+v2; pf[f'{k}_diff'] = abs(v1-v2)
            ow1 = feats_h.get(h1,{}).get('win_odds_3min',0); ow2 = feats_h.get(h2,{}).get('win_odds_3min',0)
            pf['win_odds_ratio'] = min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
            pf['win_odds_sum_inv'] = (1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
            um_X.append([pf.get(k,0) for k in um_fnames])
            um_init.append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            um_meta_local.append('-'.join(str(x) for x in sorted([h1,h2])))
            um_est_odds_list.append((1/sh_p)*(1-TAKEOUT['umaren']))
        if um_X:
            um_X = np.array(um_X, dtype=np.float32)
            um_init = np.array(um_init, dtype=np.float64)
            um_raw = um_model.predict(um_X, raw_score=True)
            um_s = um_b * um_init + um_tau * um_raw
            um_s -= um_s.max()
            um_probs = np.exp(um_s) / np.exp(um_s).sum()
            for i in range(len(um_meta_local)):
                raw_est = um_est_odds_list[i]
                cal_est = apply_odds_calibration(raw_est, um_cal)
                ev = um_probs[i] * cal_est
                if ev >= ev_threshold:
                    um_cands.append({
                        'combo': um_meta_local[i], 'ev': float(ev),
                        'model_prob': float(um_probs[i]), 'est_odds': float(cal_est),
                        'bet_type': 'umaren',
                    })
    else:
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

    # --- 三連複（トリオ残差モデル + 補正）---
    trio_cands = []
    tr_model = exotic_models.get('trio') if exotic_models else trio_model
    tr_info = exotic_config.get('models',{}).get('trio',{}) if exotic_config else (trio_config or {})
    tr_cal = exotic_config.get('odds_calibration',{}).get('sanrenpuku',[]) if exotic_config else []

    if tr_model and tr_info and race_data:
        from realtime_bet import predict_trio
        tr_cfg = {**exotic_config, **tr_info} if exotic_config else trio_config
        trio_preds = predict_trio(race_data, odds_5min, odds_3min, tr_model, tr_cfg)
        for tp in trio_preds:
            cal_odds = apply_odds_calibration(tp['est_odds'], tr_cal)
            tp['ev'] = tp['model_prob'] * cal_odds
            tp['est_odds'] = cal_odds
            if tp['ev'] >= ev_threshold:
                trio_cands.append(tp)
    else:
        for a, b, c in combinations(top8_idx, 3):
            key = tuple(sorted([a, b, c]))
            sh_p = trio_p.get(key, 0)
            if sh_p <= 0: continue
            est_odds = (1/sh_p) * (1-TAKEOUT['sanrenpuku'])
            cal_odds = apply_odds_calibration(est_odds, tr_cal)
            ev = sh_p * cal_odds
            if ev >= ev_threshold:
                h1, h2, h3 = horses[a], horses[b], horses[c]
                trio_cands.append({
                    'combo': '-'.join(str(x) for x in sorted([h1, h2, h3])),
                    'ev': float(ev), 'model_prob': float(sh_p),
                    'est_odds': float(cal_odds), 'bet_type': 'sanrenpuku',
                })
    trio_cands.sort(key=lambda x: -x['ev'])
    candidates['sanrenpuku'] = trio_cands

    # --- 三連単（上位8頭のフル順列、1番人気含む組のみ）---
    st_cands = []
    st_model = exotic_models.get('trifecta') if exotic_models else None
    st_info = exotic_config.get('models',{}).get('trifecta',{}) if exotic_config else {}
    st_cal = exotic_config.get('odds_calibration',{}).get('sanrentan',[]) if exotic_config else []

    if st_model and st_info:
        st_fnames = st_info['feature_names']
        st_b = st_info['b']; st_tau = st_info['tau']
        st_X = []; st_init = []; st_meta_local = []; st_est_list = []
        for a_i, b_i, c_i in permutations(top8_idx, 3):
            # 1番人気含む組のみ
            if top1_idx not in (a_i, b_i, c_i):
                continue
            key = (a_i, b_i, c_i)
            sh_p = trifecta_p.get(key, 0)
            if sh_p <= 0: continue
            h1, h2, h3 = horses[a_i], horses[b_i], horses[c_i]
            pf = {}
            f1 = feats_h.get(h1,{}); f2 = feats_h.get(h2,{}); f3 = feats_h.get(h3,{})
            for k in FEAT_KEYS_PAIR:
                v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
            pf['first_odds']=f1.get('win_odds_3min',0)
            pf['second_odds']=f2.get('win_odds_3min',0)
            pf['third_odds']=f3.get('win_odds_3min',0)
            st_X.append([pf.get(k,0) for k in st_fnames])
            st_init.append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            st_meta_local.append(f'{h1}-{h2}-{h3}')
            st_est_list.append((1/sh_p)*(1-TAKEOUT['sanrentan']))
        if st_X:
            st_X = np.array(st_X, dtype=np.float32)
            st_init = np.array(st_init, dtype=np.float64)
            st_raw = st_model.predict(st_X, raw_score=True)
            st_s = st_b * st_init + st_tau * st_raw
            st_s -= st_s.max()
            st_probs = np.exp(st_s) / np.exp(st_s).sum()
            for i in range(len(st_meta_local)):
                raw_est = st_est_list[i]
                cal_est = apply_odds_calibration(raw_est, st_cal)
                ev = st_probs[i] * cal_est
                if ev >= ev_threshold:
                    st_cands.append({
                        'combo': st_meta_local[i], 'ev': float(ev),
                        'model_prob': float(st_probs[i]), 'est_odds': float(cal_est),
                        'bet_type': 'sanrentan',
                    })
    else:
        # モデルなし: SH確率のみ（1番人気含む全順列）
        for a_i, b_i, c_i in permutations(top8_idx, 3):
            if top1_idx not in (a_i, b_i, c_i):
                continue
            key = (a_i, b_i, c_i)
            sh_p = trifecta_p.get(key, 0)
            if sh_p <= 0: continue
            est_odds = (1/sh_p) * (1-TAKEOUT['sanrentan'])
            cal_odds = apply_odds_calibration(est_odds, st_cal)
            ev = sh_p * cal_odds
            if ev >= ev_threshold:
                h1, h2, h3 = horses[a_i], horses[b_i], horses[c_i]
                st_cands.append({
                    'combo': f'{h1}-{h2}-{h3}',
                    'ev': float(ev), 'model_prob': float(sh_p),
                    'est_odds': float(cal_odds), 'bet_type': 'sanrentan',
                })
    st_cands.sort(key=lambda x: -x['ev'])
    candidates['sanrentan'] = st_cands

    # --- 馬単（1着固定、top1確率>=30%のとき）---
    ut_cands = []
    if top1_prob >= 0.30:
        for p_i in top8_idx:
            if p_i == top1_idx: continue
            key = (top1_idx, p_i)
            sh_p = umatan_p.get(key, 0)
            if sh_p <= 0: continue
            est_odds = (1/sh_p) * (1-TAKEOUT['umatan'])
            ev = sh_p * est_odds
            if ev >= ev_threshold:
                ut_cands.append({
                    'combo': f'{top1_hn}-{horses[p_i]}',
                    'ev': float(ev), 'model_prob': float(sh_p),
                    'est_odds': float(est_odds), 'bet_type': 'umatan',
                })
    ut_cands.sort(key=lambda x: -x['ev'])
    candidates['umatan'] = ut_cands

    # === 券種選択ロジック ===
    # ポートフォリオ戦略: 三連複+三連単の同時購入（ROI 130.0%, 利益5.7倍）
    # フォールバック: どちらかのみ → 単勝
    best_type = None
    best_bets = []
    best_reason = 'EV>=閾値の組合せなし'

    trio_c = candidates.get('sanrenpuku', [])
    trifecta_c = candidates.get('sanrentan', [])
    win_c = candidates.get('win', [])

    # 優先度1: 三連複+三連単の同時購入
    if trio_c or trifecta_c:
        combined = []
        for c in trio_c:
            combined.append(c)
        for c in trifecta_c:
            combined.append(c)

        if combined:
            n_bets = len(combined)
            per_bet = max(100, (race_budget // n_bets // 100) * 100)
            for b in combined:
                b['amount'] = per_bet

            # 券種を'portfolio'として返す（三連複+三連単の混合）
            best_type = 'portfolio'
            best_bets = combined
            n_trio = len(trio_c)
            n_tri = len(trifecta_c)
            avg_ev = np.mean([c['ev'] for c in combined])
            expected_profit = sum(c['ev'] * per_bet for c in combined) - n_bets * per_bet
            best_reason = (f'三連複{n_trio}点+三連単{n_tri}点={n_bets}点 '
                          f'期待利益={expected_profit:.0f}円 '
                          f'avg_EV={avg_ev:.2f} '
                          f'top1確率={top1_prob:.1%}')

    # フォールバック: 単勝のみ（連系が0のとき）
    if not best_bets and win_c:
        best_type = 'win'
        best_bets = win_c
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
        'top1_prob': float(top1_prob),
        'top1_hn': int(top1_hn),
    }


# 券種名の日本語マッピング
BET_TYPE_JP = {
    'win': '単勝',
    'umaren': '馬連',
    'umatan': '馬単',
    'sanrenpuku': '三連複',
    'sanrentan': '三連単',
    'portfolio': '三連複+三連単',
}
