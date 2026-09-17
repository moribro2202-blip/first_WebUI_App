# -*- coding: utf-8 -*-
"""リアルタイム自動投票パイプライン v22
単勝 + 三連複（ペーパー）

使い方（ターミナルから直接起動すること。Claude Codeのバックグラウンドタスクは10分で停止する）:
  python scripts/production/realtime_bet.py              # ペーパートレード
  python scripts/production/realtime_bet.py --live        # 実投票（単勝のみ。三連複はペーパー）
  python scripts/production/realtime_bet.py --dry-run     # 即座に全レース処理（テスト用）

注意:
  - 必ずターミナルから起動。Claude Code内のBashで起動するとタイムアウトする
  - 朝に1回起動すれば全レースを自動処理
  - 設定はDB realtime_configテーブルから読み込み
"""
import os, sys, json, math, time, sqlite3, argparse
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
LOG_DIR = os.path.join(BASE, 'data', 'realtime_log')
os.makedirs(LOG_DIR, exist_ok=True)

from ipat_voter import IPATVoter, load_env
import threading

# 即PATのPlaywright操作をスレッドセーフにするロック
voter_lock = threading.Lock()

# === 設定 ===
EV_THRESHOLD = 1.20      # Fable推奨: Winner's Curse補正（条件付き比0.85）
ODDS_MIN = 2.0
ODDS_MAX = 40.0           # 2026-09-12 Fable Go: 2-40x（40-50x帯はrec97.9%で除外。差し戻し条件: 30-40x帯500点でrec<85% or WC<0.7）
T_EARLY = 5 * 60         # 5分前（秒）— 締切基準
T_LATE = 1 * 60          # 1分前（秒）— 締切基準
BET_AMOUNT = 100          # 100円（テスト用）
BETA = 1.015

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"  [{ts}] {msg}", flush=True)


def load_model():
    """本番モデル（単勝）をロード"""
    import lightgbm as lgb
    config_path = os.path.join(MODEL_DIR, 'prod_config.json')
    if not os.path.exists(config_path):
        raise FileNotFoundError("prod_config.json がありません。train_and_save_model.py を実行してください。")
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    model = lgb.Booster(model_file=os.path.join(MODEL_DIR, config['model_file']))
    with open(os.path.join(MODEL_DIR, config['stats_file']), 'r', encoding='utf-8') as f:
        stats = json.load(f)
    return model, config, stats


def load_trio_model():
    """三連複トリオ残差モデルをロード"""
    import lightgbm as lgb
    config_path = os.path.join(MODEL_DIR, 'prod_trio_config_v22.json')
    if not os.path.exists(config_path):
        log("三連複モデルなし（prod_trio_config_v22.json）")
        return None, None
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    model = lgb.Booster(model_file=os.path.join(MODEL_DIR, config['model_file']))
    return model, config


def load_exotic_models():
    """全券種モデル + 補正テーブルをロード（v22g）"""
    import lightgbm as lgb
    config_path = os.path.join(MODEL_DIR, 'prod_exotic_v22g.json')
    if not os.path.exists(config_path):
        log("連系モデルなし（prod_exotic_v22g.json）")
        return None, None
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    models = {}
    for bt, info in config.get('models', {}).items():
        mpath = os.path.join(MODEL_DIR, info['model_file'])
        if os.path.exists(mpath):
            models[bt] = lgb.Booster(model_file=mpath)
            log(f"  {bt}モデルロード: b={info['b']:.3f} tau={info['tau']:.3f}")
    return models, config


def predict_trio(race_data, odds_early, odds_late, trio_model, trio_config):
    """三連複の予測（SH基準 + トリオ残差モデル）
    上位8頭のC(8,3)=56組でEV判定
    Returns: list of {combo, ev, model_prob, est_odds, horses}
    """
    from itertools import combinations as comb3

    horses = race_data['horses']
    market_probs = race_data['market_probs']
    feature_names_trio = trio_config['feature_names']
    lam2 = trio_config.get('lam2', 0.8076)
    lam3 = trio_config.get('lam3', 0.6978)
    takeout = trio_config.get('takeout', 0.25)
    b_trio = trio_config['b']
    tau_trio = trio_config['tau']
    ev_th = trio_config.get('ev_threshold', 1.2)

    n = len(horses)
    p = market_probs  # 単勝市場確率

    # SH三連複確率
    p2 = p**lam2; p3 = p**lam3
    S1 = p.sum(); S2 = p2.sum(); S3 = p3.sum()
    trio_sh = {}
    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0: continue
        for j in range(n):
            if j == i: continue
            pij = (p[i]/S1) * (p2[j]/d2)
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0: continue
            for k in range(n):
                if k in (i, j): continue
                trio_sh[tuple(sorted([i,j,k]))] = trio_sh.get(tuple(sorted([i,j,k])),0) + pij*(p3[k]/d3)

    # 上位8頭（3分前オッズ順）
    odds_sorted = sorted([(h, odds_late.get(h, 999)) for h in horses], key=lambda x: x[1])
    top8 = [h for h, _ in odds_sorted[:min(8, n)]]
    top8_idx = [horses.index(h) for h in top8]

    # 馬ごとの特徴量（race_dataから）
    X_win = race_data['X']
    win_fnames = race_data['feature_names']
    FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
                 'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
                 'top3_rate','last_fp','win_rate','is_senkou','move_5to3']

    # 馬ごとの特徴量辞書を構築
    feats_h = {}
    for i, h in enumerate(horses):
        f = {}
        for k in FEAT_KEYS:
            if k in win_fnames:
                f[k] = float(X_win[i, win_fnames.index(k)])
            else:
                f[k] = 0
        # move_5to3を実際の値で上書き
        o5 = odds_early.get(h, 0); o3 = odds_late.get(h, 0)
        f['move_5to3'] = (o5-o3)/o5 if o5>0 and o3>0 else 0
        f['win_odds_3min'] = o3
        feats_h[h] = f

    # トリオ特徴量 + SH確率でinit_score → LightGBM予測
    trio_X = []; trio_init = []; trio_meta = []; trio_odds_est = []
    for a, b, c in comb3(top8, 3):
        ai = horses.index(a); bi = horses.index(b); ci = horses.index(c)
        key = tuple(sorted([ai, bi, ci]))
        sh_p = trio_sh.get(key, 0)
        if sh_p <= 0: continue

        f1 = feats_h[a]; f2 = feats_h[b]; f3 = feats_h[c]
        pf = {}
        for k in FEAT_KEYS:
            v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
            pf[f'{k}_sum'] = v1+v2+v3; pf[f'{k}_spread'] = max(v1,v2,v3)-min(v1,v2,v3)
        odds_list = sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio'] = odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
        pf['win_odds_sum_inv'] = sum(1/o for o in odds_list if o>0)

        trio_X.append([pf.get(k, 0) for k in feature_names_trio])
        trio_init.append(math.log(max(sh_p, 1e-15)) - math.log(max(1-sh_p, 1e-15)))
        combo = '-'.join(str(x) for x in sorted([a, b, c]))
        trio_meta.append(combo)
        trio_odds_est.append((1/sh_p) * (1-takeout))

    if not trio_X:
        return []

    trio_X = np.array(trio_X, dtype=np.float32)
    trio_init = np.array(trio_init, dtype=np.float64)
    raw = trio_model.predict(trio_X, raw_score=True)
    s = b_trio * trio_init + tau_trio * raw
    s -= s.max()
    probs = np.exp(s) / np.exp(s).sum()

    results = []
    for i in range(len(trio_meta)):
        est_odds = trio_odds_est[i]
        ev = probs[i] * est_odds
        results.append({
            'combo': trio_meta[i],
            'ev': float(ev),
            'model_prob': float(probs[i]),
            'est_odds': float(est_odds),
            'bet_type': 'sanrenpuku',
        })

    results.sort(key=lambda x: -x['ev'])
    return results


def load_race_schedule(today_str):
    """DBから今日のレーススケジュールを取得"""
    db = sqlite3.connect(DB_PATH)
    races = []
    for row in db.execute(
        'SELECT race_id, venue_code, venue_name, race_number, surface, distance, '
        'track_condition, grade, start_time, race_name '
        'FROM races WHERE race_date=? ORDER BY start_time, venue_code, race_number',
        (today_str,)
    ).fetchall():
        rid, vc, vn, rn, sf, dist, tc, grade, st, rname = row
        # エントリー取得
        entries = {}
        for e in db.execute(
            'SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,'
            'rider_index,run_style,carried_weight FROM entries WHERE race_id=?', (rid,)
        ).fetchall():
            entries[e[0]] = {
                'hid': e[1], 'jockey': e[2], 'trainer': e[3], 'idm': e[4],
                'total': e[5], 'rider': e[6], 'run_style': e[7], 'weight': e[8]
            }
        # 前日オッズ
        oz = {}
        for o in db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall():
            try: oz[int(o[0])] = o[1]
            except: pass

        if entries and st:
            races.append({
                'race_id': rid, 'venue_code': vc, 'venue_name': vn,
                'race_number': rn, 'surface': sf, 'distance': dist,
                'track_condition': tc, 'grade': grade, 'start_time': st,
                'race_name': rname or '', 'entries': entries, 'oz': oz,
            })
    db.close()
    return races


def calibrate_probs(raw_probs, calibration):
    """オッズ帯別キャリブレーション補正
    logit(p_cal) = a0 + a1*logit(p) + a2*logit(p)^2
    """
    if calibration is None:
        return raw_probs
    a0 = calibration.get('a0') or calibration.get('intercept', 0)
    a1 = calibration.get('a1') or calibration.get('coef1', 1)
    a2 = calibration.get('a2') or calibration.get('coef2', 0)
    clipped = np.clip(raw_probs, 1e-6, 1 - 1e-6)
    lp = np.log(clipped / (1 - clipped))  # logit
    cal_logit = a0 + a1 * lp + a2 * lp ** 2
    cal_p = 1 / (1 + np.exp(-cal_logit))  # expit
    cal_p = cal_p / cal_p.sum()  # 再正規化
    return cal_p


def build_features(race, odds_now, model_config, stats):
    """特徴量構築（move特徴量は後で埋める）"""
    entries = race['entries']
    horses = sorted(entries.keys())
    n = len(horses)
    if n < 5:
        return None

    sf = race['surface']; dist = race['distance']
    tc = race['track_condition'] or '良'
    grade = race['grade'] or '一般'

    # 市場確率（現在のオッズから）
    inv = np.array([1 / odds_now.get(h, 999) for h in horses])
    s = inv.sum()
    if s == 0:
        return None
    mp = inv / s
    mp = mp ** BETA
    mp /= mp.sum()
    # 較正は市場確率ではなくモデル出力に適用するため、ここでは掛けない

    # 前日オッズ
    oz = race['oz']
    oz_inv = {h: 1/oz[h] if h in oz and oz[h] > 0 else 0 for h in horses}
    mk_inv = {h: 1/odds_now.get(h, 999) for h in horses}
    oz_sum = sum(oz_inv.values()) or 1
    mk_sum = sum(mk_inv.values()) or 1

    idms = [entries.get(h, {}).get('idm') or 50 for h in horses]
    avg_idm = np.mean(idms)
    riders = [entries.get(h, {}).get('rider') or 0 for h in horses]
    avg_rider = np.mean(riders)

    feature_names = model_config['feature_names']
    X = []
    init_scores = []

    for i, h in enumerate(horses):
        ent = entries.get(h, {})
        hid = ent.get('hid', '')
        idm = ent.get('idm') or 50
        rider = ent.get('rider') or 0
        jn = ent.get('jockey', '')
        tn = ent.get('trainer', '')

        f = {}
        f['idm_c'] = idm - avg_idm
        f['rider_c'] = rider - avg_rider
        f['total_index'] = ent.get('total') or 0
        oz_p = oz_inv.get(h, 0) / oz_sum
        mk_p = mk_inv.get(h, 0) / mk_sum
        f['expert_resid'] = math.log(max(oz_p, 1e-6)) - math.log(max(mk_p, 1e-6)) if oz_p > 0 and mk_p > 0 else 0

        js = stats.get('jockey_stats', {}).get(jn, {})
        f['jockey_t3rate'] = js.get('t3', 0) / js['r'] if js.get('r', 0) >= 30 else -1
        ts = stats.get('trainer_stats', {}).get(tn, {})
        f['trainer_t3rate'] = ts.get('t3', 0) / ts['r'] if ts.get('r', 0) >= 30 else -1

        runs = stats.get('horse_history', {}).get(hid, [])
        f['horse_runs'] = len(runs)
        if runs:
            rc = runs[-5:]
            f['avg_fp_5'] = np.mean([r['fp'] for r in rc])
            f['top3_rate'] = sum(1 for r in runs if r['fp'] <= 3) / len(runs)
            f['last_fp'] = runs[-1]['fp']
            dr = [r for r in runs if abs(r.get('dist', 0) - dist) <= 200]
            f['dist_t3rate'] = sum(1 for r in dr if r['fp'] <= 3) / len(dr) if dr else -1
            sr = [r for r in runs if r.get('surface') == sf]
            f['surf_t3rate'] = sum(1 for r in sr if r['fp'] <= 3) / len(sr) if sr else -1
            f['trend'] = runs[-3]['fp'] - runs[-1]['fp'] if len(runs) >= 3 else 0
            f['win_rate'] = sum(1 for r in runs if r['fp'] == 1) / len(runs) if len(runs) >= 5 else -1
        else:
            f.update({'avg_fp_5': 8, 'top3_rate': 0, 'last_fp': 8, 'dist_t3rate': -1,
                      'surf_t3rate': -1, 'trend': 0, 'win_rate': -1})

        f['nhead'] = n
        f['distance'] = dist
        f['surface'] = sf_map.get(sf, 0)
        f['track_cond'] = tc_map.get(tc, 0)
        f['grade'] = grade_map.get(grade, 0)
        f['is_senkou'] = 1 if ent.get('run_style', '') in ('逃げ', '先行') else 0
        f['gate_ratio'] = h / n
        cw = ent.get('weight') or 0
        avg_cw = np.mean([entries.get(h2, {}).get('weight') or 0 for h2 in horses])
        f['weight_c'] = (cw - avg_cw) if cw > 0 else 0
        # move特徴量（後で埋める）
        move_name = model_config.get('move_feature', 'move_5to3')
        f[move_name] = 0
        # CYB（JRDBインポート済みなら取得）
        f['cyb_c'] = 0  # TODO: CYBデータから取得

        X.append([f.get(k, 0) for k in feature_names])
        p = mp[i]
        init_scores.append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))

    return {
        'horses': horses, 'X': np.array(X, dtype=np.float32),
        'init_scores': np.array(init_scores, dtype=np.float64),
        'market_probs': mp, 'feature_names': feature_names,
    }


def predict_with_move(race_data, odds_early, odds_late, model, config):
    """move特徴量を埋めて予測（較正適用済み）"""
    X = race_data['X'].copy()
    horses = race_data['horses']
    feature_names = race_data['feature_names']

    # move特徴量名をconfigから取得
    move_name = config.get('move_feature', 'move_5to3')
    move_idx = feature_names.index(move_name)

    for i, h in enumerate(horses):
        o5 = odds_early.get(h, 0)
        o_late = odds_late.get(h, 0)
        if o5 > 0 and o_late > 0:
            X[i, move_idx] = (o5 - o_late) / o5
        else:
            X[i, move_idx] = 0

    b = config['b']
    tau = config['tau']
    init = race_data['init_scores']

    raw = model.predict(X, raw_score=True)
    s = b * init + tau * raw
    s -= s.max()
    probs = np.exp(s) / np.exp(s).sum()

    # 較正をモデル出力に適用（v15検証通り）
    cal = config.get('calibration')
    if cal:
        probs_cal = calibrate_probs(probs, cal)
    else:
        probs_cal = probs

    results = []
    for i, h in enumerate(horses):
        o = odds_late.get(h, 0)
        ev = probs_cal[i] * o if o > 0 else 0
        move = X[i, move_idx]
        results.append({
            'horse_number': h, 'odds': o, 'model_prob': float(probs_cal[i]),
            'ev': float(ev), 'move': float(move),
        })

    results.sort(key=lambda x: -x['ev'])
    return results


def save_log(race, odds_snapshots, predictions, bets, timestamps, bet_amount=BET_AMOUNT):
    """ログ保存（JSONL + DB）"""
    today_str = datetime.now().strftime('%Y-%m-%d')
    rid = race['race_id']
    vn = race['venue_name']
    rn = race['race_number']
    dl = race.get('deadline', '')

    # JSONL（従来のログ）
    record = {
        'timestamp': datetime.now().isoformat(),
        'race_id': rid, 'venue': vn, 'race_number': rn,
        'deadline': dl, 'start_time': race['start_time'],
        'surface': race['surface'], 'distance': race['distance'],
        'odds_snapshots': {
            label: {str(k): v for k, v in odds.items()}
            for label, odds in odds_snapshots.items()
        },
        'predictions': predictions[:5],
        'bets': bets,
        'timestamps': timestamps,
    }
    log_path = os.path.join(LOG_DIR, f'rt_{datetime.now().strftime("%Y%m%d")}.jsonl')
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False) + '\n')

    # DB保存
    try:
        db = sqlite3.connect(DB_PATH)

        # realtime_odds: 全スナップショットの全馬オッズ（重複防止）
        for label, odds in odds_snapshots.items():
            existing = db.execute(
                'SELECT COUNT(*) FROM realtime_odds WHERE race_id=? AND snapshot_label=?',
                (rid, label)
            ).fetchone()[0]
            if existing > 0:
                continue
            snap_time = timestamps.get(f'{label}_done', datetime.now().isoformat())
            for hn, o in odds.items():
                db.execute(
                    'INSERT OR IGNORE INTO realtime_odds (race_id,race_date,venue_name,race_number,deadline,snapshot_label,snapshot_time,horse_number,odds) VALUES (?,?,?,?,?,?,?,?,?)',
                    (rid, today_str, vn, rn, dl, label, snap_time, hn, o)
                )

        # realtime_predictions: 全馬の予測（top10）— レースごとに1回だけ
        existing = db.execute('SELECT COUNT(*) FROM realtime_predictions WHERE race_id=?', (rid,)).fetchone()[0]
        if existing == 0:
            for pred in (predictions or [])[:10]:
                should_bet = 1 if any(b['horse_number'] == pred['horse_number'] for b in bets) else 0
                db.execute(
                    'INSERT INTO realtime_predictions (race_id,race_date,venue_name,race_number,horse_number,odds,model_prob,ev,move,should_bet) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (rid, today_str, vn, rn, pred['horse_number'], pred.get('odds', 0),
                     pred.get('model_prob', 0), pred.get('ev', 0), pred.get('move', 0), should_bet)
                )
            log(f"  DB: {vn}{rn}R predictions {len(predictions or [])}件保存")

        # realtime_bets: 投票記録（ペーパー/実投票とも記録）— 重複防止
        existing_bets = db.execute(
            'SELECT COUNT(*) FROM realtime_bets WHERE race_id=?', (rid,)
        ).fetchone()[0]
        if existing_bets > 0:
            log(f"  DB: {vn}{rn}R bets already recorded ({existing_bets}件), skipping")
        elif bets:
            for bet in bets:
                db.execute(
                    'INSERT INTO realtime_bets (race_id,race_date,venue_name,race_number,horse_number,amount,odds_at_bet,model_prob,ev,move,status,is_live) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (rid, today_str, vn, rn, bet['horse_number'], bet_amount,
                     bet['odds'], bet['model_prob'], bet['ev'], bet['move'],
                     bet.get('status', 'paper'), bet.get('is_live', 0))
                )
            log(f"  DB: {vn}{rn}R bets {len(bets)}件保存")
        else:
            # 投票なしも記録（top1のEVを記録）
            if predictions:
                top = predictions[0]
                db.execute(
                    'INSERT INTO realtime_bets (race_id,race_date,venue_name,race_number,horse_number,amount,odds_at_bet,model_prob,ev,move,status,is_live) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (rid, today_str, vn, rn, top['horse_number'], 0,
                     top.get('odds', 0), top.get('model_prob', 0), top.get('ev', 0), top.get('move', 0),
                     'no_bet', 0)
                )
            log(f"  DB: {vn}{rn}R no_bet (top EV={predictions[0]['ev']:.3f})" if predictions else f"  DB: {vn}{rn}R no_bet")

        db.commit()
        db.close()
    except Exception as e:
        import traceback
        log(f"  DB保存エラー: {e}")
        log(f"  {traceback.format_exc()}")


def fetch_confirmed_odds_from_jrdb(race_date, rid):
    """JRDBの直前情報ページからレース後の確定オッズを取得"""
    try:
        from jrdb_paddock import JRDBPaddockScraper
        scraper = JRDBPaddockScraper(headless=True)
        scraper.start()
        data = scraper.fetch_race(race_date, rid)
        scraper.close()
        if not data:
            return {}
        odds = {}
        for entry in data:
            hn = entry.get('horse_number')
            tan = entry.get('tan_odds')
            if hn and tan and tan > 0:
                odds[hn] = tan
        return odds
    except Exception as e:
        log(f"  [確定オッズ] JRDB取得エラー: {e}")
        return {}


def check_result(race, confirmed_odds_ipat=None):
    """レース結果をDBから確認して投票記録を更新（スレッドセーフ）
    JRDBから確定オッズも取得してrealtime_oddsに'confirmed'として記録
    即PATからの確定オッズをフォールバックとして使用
    """
    rid = race['race_id']
    vn = race['venue_name']
    rn = race['race_number']
    label = f"{vn}{rn}R"
    today_str = datetime.now().strftime('%Y-%m-%d')

    try:
        # 確定オッズ取得: 即PAT優先 → JRDBフォールバック
        log(f"  [結果] {label} 確定オッズ取得中...")
        confirmed_odds = {}
        if confirmed_odds_ipat:
            confirmed_odds = confirmed_odds_ipat
            log(f"  [結果] {label} 確定オッズ取得(即PAT): {len(confirmed_odds)}頭")
        else:
            confirmed_odds = fetch_confirmed_odds_from_jrdb(today_str, rid)
            if confirmed_odds:
                log(f"  [結果] {label} 確定オッズ取得(JRDB): {len(confirmed_odds)}頭")
            else:
                log(f"  [結果] {label} 確定オッズ取得失敗")

        db = sqlite3.connect(DB_PATH)

        # 確定オッズをrealtime_oddsに'confirmed'ラベルで保存
        if confirmed_odds:
            dl = race.get('deadline', '')
            for hn, odds in confirmed_odds.items():
                db.execute(
                    'INSERT OR IGNORE INTO realtime_odds '
                    '(race_id,race_date,venue_name,race_number,deadline,snapshot_label,snapshot_time,horse_number,odds) '
                    'VALUES (?,?,?,?,?,?,?,?,?)',
                    (rid, today_str, vn, rn, dl, 'confirmed', datetime.now().isoformat(), hn, odds)
                )

        # 1着馬を確定オッズから特定（最も人気のある馬ではなく、結果テーブルから）
        result_row = db.execute(
            'SELECT horse_number, finish_position FROM results WHERE race_id=? AND finish_position=1',
            (rid,)
        ).fetchone()

        # resultsテーブルにまだ結果がない場合はスキップ
        if not result_row:
            # 確定オッズは保存済みなのでcommitしてreturn
            db.commit()
            db.close()
            log(f"  [結果] {label} 着順未確定（確定オッズは記録済み）")
            return

        winner_num = result_row[0]
        winner_odds = confirmed_odds.get(winner_num, 0)
        log(f"  [結果] {label} 1着: 馬番{winner_num} 確定オッズ{winner_odds:.1f}倍")

        # realtime_results に記録（確定オッズ付き）
        db.execute(
            'INSERT OR REPLACE INTO realtime_results '
            '(race_id,race_date,venue_name,race_number,winner_number,winner_odds,checked_at) '
            'VALUES (?,?,?,?,?,?,?)',
            (rid, today_str, vn, rn, winner_num, winner_odds, datetime.now().isoformat())
        )

        # 投票記録を更新（確定オッズで払戻計算）
        bets = db.execute(
            'SELECT id, horse_number, amount, odds_at_bet FROM realtime_bets WHERE race_id=? AND result IS NULL AND status != ?',
            (rid, 'no_bet')
        ).fetchall()

        for bet_id, bet_hn, bet_amount, bet_odds in bets:
            is_hit = (bet_hn == winner_num)
            # 確定オッズがあればそちらで払戻計算、なければ投票時オッズ
            actual_odds = confirmed_odds.get(bet_hn, bet_odds) if is_hit else 0
            payout = actual_odds * bet_amount if is_hit else 0
            result_str = 'hit' if is_hit else 'miss'
            db.execute(
                'UPDATE realtime_bets SET result=?, payout=?, confirmed_odds=?, winner_number=?, settled_at=? WHERE id=?',
                (result_str, payout, confirmed_odds.get(bet_hn), winner_num, datetime.now().isoformat(), bet_id)
            )
            if is_hit:
                log(f"  [結果] {label} 馬番{bet_hn} ★的中！ 確定{actual_odds:.1f}倍 払戻{payout:.0f}円")
            else:
                log(f"  [結果] {label} 馬番{bet_hn} ハズレ（1着: 馬番{winner_num}）")

        db.commit()
        db.close()

    except Exception as e:
        import traceback
        log(f"  [結果] {label} 結果確認エラー: {e}")
        log(f"  {traceback.format_exc()}")


def schedule_result_check(race, delay_seconds, voter=None):
    """指定秒数後にレース結果を確認する"""
    def _check():
        time.sleep(delay_seconds)
        label = f"{race['venue_name']}{race['race_number']}R"
        log(f"  [結果確認] {label} 結果取得開始...")

        # 即PATから確定オッズを取得（ロックで排他制御）
        confirmed_odds_ipat = {}
        if voter:
            try:
                with voter_lock:
                    odds = voter.get_odds(race['venue_name'], race['race_number'])
                if odds:
                    confirmed_odds_ipat = odds
                    log(f"  [結果確認] {label} 即PATから確定オッズ取得: {len(odds)}頭")
            except Exception as e:
                log(f"  [結果確認] {label} 即PAT確定オッズ取得失敗: {e}")

        check_result(race, confirmed_odds_ipat=confirmed_odds_ipat)

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    return t


def parse_time_str(t_str):
    """'HH:MM' → datetime (today)"""
    today = datetime.now().date()
    h, m = int(t_str[:2]), int(t_str[3:5])
    return datetime(today.year, today.month, today.day, h, m)


def get_deadlines_from_ipat(voter, venue_name):
    """即PATからレース締切時刻を取得"""
    import re
    voter._go_to_odds_page()
    voter._click_venue_button(venue_name)
    data = voter.page.evaluate('''() => {
        const result = [];
        document.querySelectorAll('button').forEach(b => {
            const ng = b.getAttribute('ng-click') || '';
            const t = b.innerText.trim();
            if (ng.includes('selectRace')) result.push(t);
        });
        return result;
    }''')
    deadlines = {}
    for text in data:
        m = re.match(r'(\d+)R\s*\((\d{2}:\d{2})\)', text.replace('\n', ' '))
        if m:
            deadlines[int(m.group(1))] = m.group(2)
    return deadlines


def main():
    parser = argparse.ArgumentParser(description='リアルタイム自動投票')
    parser.add_argument('--live', action='store_true', help='実投票する')
    parser.add_argument('--dry-run', action='store_true', help='即座に全レース処理（待機なし）')
    parser.add_argument('--t-early', type=int, default=5, help='早い方のオッズ取得（分前、デフォルト5）')
    parser.add_argument('--t-late', type=int, default=1, help='遅い方のオッズ取得（分前、デフォルト1）')
    parser.add_argument('--threshold', type=float, default=1.20, help='EV閾値（デフォルト1.20）')
    parser.add_argument('--amount', type=int, default=100, help='ベット額（デフォルト100円）')
    args = parser.parse_args()

    # DB realtime_config から設定を読み込み（UIの設定に従う）
    db_conf = sqlite3.connect(DB_PATH)
    rt_config = {}
    try:
        for row in db_conf.execute('SELECT key, value FROM realtime_config').fetchall():
            rt_config[row[0]] = row[1]
    except:
        pass
    db_conf.close()

    # コマンドライン引数よりDBの設定を優先（引数はフォールバック）
    is_live = rt_config.get('mode') == 'live' or args.live
    ev_threshold = float(rt_config.get('ev_threshold', args.threshold))
    race_budget = int(rt_config.get('amount', args.amount))  # 1レースあたりの予算

    print("=" * 60)
    print(f"  リアルタイム自動投票パイプライン v22")
    print(f"  モード: {'★実投票★' if is_live else 'ペーパートレード'}")
    print(f"  設定ソース: DB realtime_config")
    print(f"  オッズ取得: 発走5/4/3/2/1分前（5時点）")
    print(f"  判定: 発走3分前（move_5to3）")
    print(f"  EV閾値: {ev_threshold}  オッズ帯: {ODDS_MIN}-{ODDS_MAX}倍")
    print(f"  1レース予算: {race_budget}円（点数で均等配分、100円単位切り下げ）")
    print("=" * 60)

    # モデルロード
    log("モデルロード中...")
    model, config, stats = load_model()
    log(f"単勝モデルロード完了 (b={config['b']:.3f}, τ={config['tau']:.3f})")

    # 全券種モデルロード（v22g）
    exotic_models, exotic_config = load_exotic_models()
    if exotic_models:
        log(f"連系モデルロード完了: {list(exotic_models.keys())}")
    else:
        log("連系モデルなし（単勝のみ）")
    # 後方互換
    trio_model = exotic_models.get('trio') if exotic_models else None
    trio_config = None
    if exotic_config and 'models' in exotic_config and 'trio' in exotic_config['models']:
        trio_config = {**exotic_config, **exotic_config['models']['trio']}

    # 今日のレーススケジュール
    today_str = datetime.now().strftime('%Y-%m-%d')
    races = load_race_schedule(today_str)
    if not races:
        log(f"今日({today_str})のレースがDBにありません。jrdb_import.py を実行してください。")
        return
    log(f"本日のレース: {len(races)}R")

    # JRDBパドックスクレイパー（遅延初期化、JRDB利用可能時のみ起動）
    from jrdb_paddock import JRDBPaddockScraper, save_to_db as save_paddock
    paddock_scraper = None  # 必要時に初期化

    # 即PATログイン
    log("即PATログイン中...")
    voter = IPATVoter(headless=True)
    if not voter.login():
        log("ログイン失敗")
        return
    log("ログイン成功")

    # 締切時刻を即PATから取得
    log("締切時刻取得中...")
    venue_deadlines = {}
    for vn in set(r['venue_name'] for r in races):
        dl = get_deadlines_from_ipat(voter, vn)
        venue_deadlines[vn] = dl
        log(f"  {vn}: {dl}")

    # レースに締切時刻を付与
    for race in races:
        vn = race['venue_name']
        rn = race['race_number']
        dl = venue_deadlines.get(vn, {}).get(rn)
        race['deadline'] = dl or race['start_time']

    # 発走時刻順にソート
    races.sort(key=lambda r: r['start_time'])

    for r in races:
        log(f"  {r['venue_name']}{r['race_number']:>2}R 発走{r['start_time']} (締切{r['deadline']}) {r['surface']}{r['distance']}m {r['race_name']}")

    # レースループ
    total_bet = 0
    total_payout_expected = 0
    bet_count = 0

    for race in races:
        rid = race['race_id']
        vn = race['venue_name']
        rn = race['race_number']
        dl = race['deadline']
        st = race['start_time']
        label = f"{vn}{rn}R"

        start_dt = parse_time_str(st)
        now = datetime.now()

        # 発走済みならスキップ
        if not args.dry_run and (start_dt - now).total_seconds() < 0:
            log(f"{label} 既に発走済み、スキップ")
            continue

        # === パドック気配取得（JRDB、利用可能時のみ） ===
        # Playwrightの競合を避けるため、即PATログイン後に遅延初期化
        # JRDBレートリミット中はスキップ
        if paddock_scraper is None:
            try:
                paddock_scraper = JRDBPaddockScraper(headless=True)
                paddock_scraper.start()
                log("JRDBパドックスクレイパー起動")
            except Exception as e:
                log(f"JRDBスクレイパー起動失敗（スキップ）: {e}")
                paddock_scraper = False  # 起動失敗フラグ

        if paddock_scraper and paddock_scraper is not False:
            try:
                paddock_data = paddock_scraper.fetch_race(today_str, rid)
                if paddock_data:
                    save_paddock(rid, today_str, paddock_data)
                    kehai_summary = [f'{e["horse_number"]}:{e.get("kehai_text","-")}' for e in sorted(paddock_data, key=lambda x:x['horse_number']) if e.get('kehai_text') and e['kehai_text'] != '平凡']
                    if kehai_summary:
                        log(f"{label} パドック気配: {', '.join(kehai_summary)}")
                    else:
                        log(f"{label} パドック: 全馬平凡 ({len(paddock_data)}頭)")
                else:
                    log(f"{label} パドック取得失敗")
            except Exception as e:
                log(f"{label} パドック取得エラー: {e}")

        # === 発走5分前まで待機 ===
        if not args.dry_run:
            t5_dt = start_dt - timedelta(minutes=5)
            wait = (t5_dt - now).total_seconds()
            if wait > 0:
                log(f"{label} 発走{st} — 5分前まで{wait:.0f}秒待機")
                # ハートビート: 60秒ごとに生存表示
                remaining = wait
                while remaining > 60:
                    time.sleep(60)
                    remaining -= 60
                    mins_left = remaining / 60
                    log(f"  ⏳ {label}まで{mins_left:.0f}分 (稼働中)")
                if remaining > 0:
                    time.sleep(remaining)

        # === 5時点のオッズ取得: 発走5/4/3/2/1分前（即PATから取得） ===
        odds_all = {}
        timestamps = {'start_time': st, 'deadline': dl}

        for mins_before in [5, 4, 3, 2, 1]:
            snap_label = f'{mins_before}min'

            if not args.dry_run and mins_before < 5:
                target_dt = start_dt - timedelta(minutes=mins_before)
                wait = (target_dt - datetime.now()).total_seconds()
                if wait > 0:
                    time.sleep(wait)

            ts_start = datetime.now()
            with voter_lock:
                if mins_before == 5:
                    odds = voter.get_odds(vn, rn)
                else:
                    odds = voter.refresh_odds_on_page(rn)
                    if not odds:
                        log(f"{label} 発走{mins_before}分前 軽量取得失敗、フルナビで再試行")
                        odds = voter.get_odds(vn, rn)
            ts_done = datetime.now()

            if odds:
                odds_all[snap_label] = odds
                log(f"{label} 発走{mins_before}分前 {len(odds)}頭 ({(ts_done-ts_start).total_seconds():.1f}秒)")
            else:
                log(f"{label} 発走{mins_before}分前 取得失敗")

            timestamps[f'{snap_label}_start'] = ts_start.isoformat()
            timestamps[f'{snap_label}_done'] = ts_done.isoformat()

        if '5min' not in odds_all:
            log(f"{label} 5分前オッズなし、スキップ")
            continue

        # 判定用オッズ: 3分前（なければ最も近い時点）
        odds_judge = odds_all.get('3min', odds_all.get('2min', odds_all.get('1min', odds_all['5min'])))
        odds_early = odds_all['5min']

        # 特徴量構築（3分前オッズで市場確率）
        race_data = build_features(race, odds_judge, config, stats)
        if race_data is None:
            log(f"{label} 特徴量構築失敗、スキップ")
            continue

        # === 予測（move_5to3 = 発走5分前 → 3分前） ===
        predictions = predict_with_move(race_data, odds_early, odds_judge, model, config)

        # === 券種自動選択 ===
        from bet_selector import select_best_bets, BET_TYPE_JP

        # モデル勝率を取得
        horses = race_data['horses']
        win_probs = np.array([p['model_prob'] for p in sorted(
            predictions, key=lambda x: horses.index(x['horse_number']))])

        selection = select_best_bets(
            horses=horses, win_probs=win_probs,
            odds_3min=odds_judge, odds_5min=odds_early,
            trio_model=trio_model, trio_config=trio_config, race_data=race_data,
            exotic_models=exotic_models, exotic_config=exotic_config,
            ev_threshold=ev_threshold, race_budget=race_budget)

        best_type = selection['best_type']
        best_bets = selection['bets']
        all_cands = selection['all_candidates']

        # 表示
        log(f"{label} {race['surface']}{race['distance']}m {race['race_name']}")
        log(f"  top1: 馬番{selection['top1_hn']} 勝率{selection['top1_prob']:.1%}")
        log(f"  候補: {' '.join(f'{BET_TYPE_JP.get(k,k)}={v}点' for k,v in all_cands.items() if v>0)}")

        # 単勝top5表示（参考）
        for pred in predictions[:5]:
            log(f"  馬番{pred['horse_number']:>2} odds={pred['odds']:>5.1f} P={pred['model_prob']:.3f} EV={pred['ev']:.3f} move={pred['move']:+.3f}")

        if best_type:
            if best_type == 'portfolio':
                n_trio = sum(1 for b in best_bets if b['bet_type'] == 'sanrenpuku')
                n_tri = sum(1 for b in best_bets if b['bet_type'] == 'sanrentan')
                log(f"  ★ ポートフォリオ: 三連複{n_trio}点+三連単{n_tri}点 — {selection['reason']}")
            else:
                bt_jp = BET_TYPE_JP.get(best_type, best_type)
                log(f"  ★ 選択: {bt_jp} {len(best_bets)}点 — {selection['reason']}")
            for b in best_bets[:5]:
                bt_jp_b = BET_TYPE_JP.get(b['bet_type'], b['bet_type'])
                log(f"    [{bt_jp_b}] {b['combo']} EV={b['ev']:.3f} P={b['model_prob']:.4f} odds≈{b['est_odds']:.0f}")
            if len(best_bets) > 5:
                log(f"    ...他{len(best_bets)-5}点")
        else:
            log(f"  → {selection['reason']}")

        # === 投票/ペーパー記録 ===
        bets = best_bets
        per_bet = bets[0]['amount'] if bets else 100

        for bet in bets:
            combo = bet['combo']
            amt = bet['amount']
            actual_bt = bet.get('bet_type', best_type)  # ポートフォリオ時は個別の券種
            ts_bet = datetime.now()

            if actual_bt == 'win' and is_live:
                # 単勝のみ実投票
                hn = int(combo)
                success, status = voter.place_bet(
                    race['venue_code'], rn, hn, amount=amt,
                    ev=bet['ev'], model_prob=bet['model_prob'], odds_1min=bet.get('est_odds', 0)
                )
                ts_bet_done = datetime.now()
                bet_time = (ts_bet_done - ts_bet).total_seconds()
                bet['status'] = 'success' if success else 'failed'
                bet['is_live'] = 1
                log(f"  -> {'OK' if success else 'NG'} {label} 馬番{hn} 単勝 {amt}円 ({bet_time:.1f}秒)")
            else:
                # 連系はペーパー記録
                bt_jp = BET_TYPE_JP.get(actual_bt, actual_bt)
                bet['status'] = f'{actual_bt}_paper'
                bet['is_live'] = 0
                log(f"  -> [PAPER] {label} {bt_jp} {combo} EV={bet['ev']:.3f} {amt}円")

            total_bet += amt
            total_payout_expected += bet['ev'] * amt
            bet_count += 1

        # DB保存（全券種のペーパー記録）
        if bets:
            try:
                db_bet = sqlite3.connect(DB_PATH)
                for bet in bets:
                    actual_bt = bet.get('bet_type', best_type or 'win')
                    db_bet.execute(
                        'INSERT INTO realtime_bets (race_id,race_date,venue_name,race_number,horse_number,bet_type,amount,odds_at_bet,model_prob,ev,move,status,is_live) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (rid, today_str, vn, rn, bet['combo'], actual_bt,
                         bet['amount'], bet.get('est_odds',0), bet['model_prob'],
                         bet['ev'], 0, bet.get('status','paper'), bet.get('is_live',0)))
                db_bet.commit()
                db_bet.close()
            except Exception as e:
                log(f"  DB保存エラー: {e}")

        # === 1分前オッズが取れていなければ再取得（投票後でもオッズは見れる） ===
        if '1min' not in odds_all:
            log(f"{label} 1分前オッズ再取得...")
            retry_odds = voter.get_odds(vn, rn)
            if retry_odds:
                odds_all['1min'] = retry_odds
                timestamps['1min_start'] = datetime.now().isoformat()
                timestamps['1min_done'] = datetime.now().isoformat()
                log(f"{label} 1分前オッズ再取得成功 {len(retry_odds)}頭")
            else:
                log(f"{label} 1分前オッズ再取得も失敗")

        # ログ保存（全時点記録）
        save_log(race, odds_all, predictions, bets, timestamps, bet_amount=per_bet if bets else 100)

        # === 発走5分後に結果確認をスケジュール ===
        if not args.dry_run:
            delay = (start_dt + timedelta(minutes=5) - datetime.now()).total_seconds()
            if delay > 0:
                schedule_result_check(race, delay, voter=voter)
                log(f"{label} 結果確認を{delay:.0f}秒後にスケジュール")

    # === 最後のレースの結果を待つ ===
    if not args.dry_run and races:
        last_start = parse_time_str(races[-1]['start_time'])
        wait_until = last_start + timedelta(minutes=10)
        wait = (wait_until - datetime.now()).total_seconds()
        if wait > 0:
            log(f"最後のレース結果確認まで{wait:.0f}秒待機...")
            time.sleep(wait)

    # === 結果集計 ===
    db = sqlite3.connect(DB_PATH)
    today_str = datetime.now().strftime('%Y-%m-%d')
    settled = db.execute(
        'SELECT horse_number, venue_name, race_number, amount, payout, result, odds_at_bet, ev '
        'FROM realtime_bets WHERE race_date=? AND result IS NOT NULL', (today_str,)
    ).fetchall()
    total_payout = sum(r[4] or 0 for r in settled)
    total_invested = sum(r[3] or 0 for r in settled)
    hits = sum(1 for r in settled if r[5] == 'hit')
    db.close()

    print()
    print("=" * 60)
    print(f"  本日の結果")
    print(f"  投票数: {bet_count}件")
    print(f"  投資額: {total_bet:,}円")
    print(f"  期待払戻: {total_payout_expected:,.0f}円")
    if total_bet > 0:
        print(f"  期待回収率: {total_payout_expected/total_bet*100:.1f}%")
    if settled:
        print(f"  --- 確定結果 ---")
        print(f"  決済済み: {len(settled)}件 (的中{hits}件)")
        print(f"  実投資額: {total_invested:,}円")
        print(f"  実払戻額: {total_payout:,.0f}円")
        if total_invested > 0:
            print(f"  実回収率: {total_payout/total_invested*100:.1f}%")
        for r in settled:
            mark = "★" if r[5] == 'hit' else "×"
            print(f"    {mark} {r[1]}{r[2]}R 馬番{r[0]} {r[3]}円 → {r[4]:.0f}円 (EV={r[7]:.3f})")
    print(f"  ログ: {LOG_DIR}")
    print("=" * 60)

    voter.close()
    if paddock_scraper and paddock_scraper is not False:
        paddock_scraper.close()
    print("Done!")


if __name__ == '__main__':
    main()
