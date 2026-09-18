# -*- coding: utf-8 -*-
"""リアルタイム競馬AI運用エンジン
開催日に実行し、各レースの直前にオッズ取得→予測→投票判断を行う。

機能:
1. 当日レーススケジュールの取得
2. 各レース発走前に5分前/1分前/30秒前オッズを取得・記録
3. モデル予測 + EV計算
4. ペーパートレード記録（or 自動投票）
5. 結果記録

使い方:
  py -3.12-32 scripts/production/realtime_runner.py [--live]
  (--live なしはペーパートレードモード)
"""
import os, sys, time, json, sqlite3, math, argparse
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
LOG_DIR = os.path.join(BASE, 'data', 'paper_trade_log')
os.makedirs(LOG_DIR, exist_ok=True)

# === JRA-VAN ===
def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0: raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def fetch_realtime_win_odds(jv, race_key):
    """リアルタイム単勝オッズを取得"""
    odds = {}
    try:
        ret = jv.JVRTOpen('0B31', race_key)
        if isinstance(ret, tuple): code = ret[0]
        else: code = ret
        if code < 0: return odds

        for _ in range(500):
            try:
                r = jv.JVRead(bytearray(200000), 200000, '')
                if isinstance(r, tuple) and len(r) >= 2:
                    rc = r[0]
                    if rc == 0: break
                    if rc == -1: continue
                    if rc > 0:
                        d = r[1]
                        if d and len(d) > 50:
                            for pos in range(43, min(len(d), 43+28*8), 8):
                                try:
                                    chunk = d[pos:pos+8]
                                    if len(chunk) >= 8:
                                        hn = int(chunk[0:2])
                                        win_odds = int(chunk[2:6]) / 10.0
                                        pop = int(chunk[6:8])
                                        if 1 <= hn <= 28 and win_odds > 0:
                                            odds[hn] = win_odds
                                except: pass
                else: break
            except: break
        try: jv.JVClose()
        except: pass
    except Exception as e:
        print(f'  [WARN] Odds fetch error: {e}')
    return odds

def jrdb_to_jravan_key(race_id, race_date):
    yy = race_id[0:2]; vv = race_id[2:4]; kk = race_id[4:6]; rr = race_id[6:8]
    kai = int(kk[0]); day = int(kk[1], 16)
    yyyy = race_date[:4]; mm = race_date[5:7]; dd = race_date[8:10]
    return f'{yyyy}{mm}{dd}{vv}{kai:02d}{day:02d}{int(rr):02d}'

# === Model ===
class PredictionEngine:
    def __init__(self):
        import lightgbm as lgb

        config_path = os.path.join(MODEL_DIR, 'prod_config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = json.load(f)

        model_path = os.path.join(MODEL_DIR, self.config['model_file'])
        self.model = lgb.Booster(model_file=model_path)
        self.feature_names = self.config['feature_names']
        self.b = self.config['b']
        self.tau = self.config['tau']
        self.beta = self.config['beta']
        self.ev_threshold = self.config['ev_threshold']

        stats_path = os.path.join(MODEL_DIR, self.config['stats_file'])
        with open(stats_path, 'r', encoding='utf-8') as f:
            self.stats = json.load(f)

        print(f'  Model loaded: b={self.b:.4f}, τ={self.tau:.4f}')

    def compute_market_probs(self, odds_dict):
        """オッズ辞書 → β補正済み市場確率"""
        horses = sorted(odds_dict.keys())
        inv = np.array([1/odds_dict[h] for h in horses])
        p = inv / inv.sum()
        p = p ** self.beta
        p = p / p.sum()
        return {h: p[i] for i, h in enumerate(horses)}

    def build_features(self, race_info, horses, odds_1min, odds_5min):
        """1レース分の特徴量を構築"""
        db = sqlite3.connect(DB_PATH)
        n = len(horses)
        sf = race_info.get('surface', '芝')
        dt = race_info.get('distance', 2000)
        tc = race_info.get('track_condition', '良')
        grade = race_info.get('grade') or '一般'

        grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
        tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
        sf_map = {'芝':0,'ダート':1}

        # Get entry data
        rid = race_info['race_id']
        entries = {}
        for row in db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?',(rid,)).fetchall():
            entries[row[0]] = {'hid':row[1],'jockey':row[2],'trainer':row[3],'idm':row[4],'total':row[5],'rider':row[6],'run_style':row[7],'weight':row[8]}

        # OZ expert odds
        oz = {}
        for row in db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall():
            try: oz[int(row[0])] = row[1]
            except: pass

        # CYB
        cyb = {}
        import glob
        for fpath in sorted(glob.glob(os.path.join(BASE,'data','jrdb','CYB','*.txt')))[-5:]:
            with open(fpath,'rb') as f:
                for line in f.readlines():
                    if len(line)<38: continue
                    raw=line.decode('ascii','replace')
                    r2=f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
                    if r2==rid:
                        try: hn_i=int(raw[8:10]); score=int(raw[33:35].strip())
                        except: continue
                        cyb[hn_i] = score

        db.close()

        # Market probs from 1min odds
        mp = self.compute_market_probs(odds_1min)

        # OZ expert probs
        oz_inv = {h:1/oz[h] for h in horses if h in oz and oz[h]>0}
        mk_inv = {h:1/odds_1min[h] for h in horses if h in odds_1min and odds_1min[h]>0}
        oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1

        idms = [entries.get(h,{}).get('idm') or 50 for h in horses]
        avg_idm = np.mean(idms)
        riders = [entries.get(h,{}).get('rider') or 0 for h in horses]
        avg_rider = np.mean(riders)
        cyb_scores = [cyb.get(h, 0) for h in horses]
        avg_cyb = np.mean(cyb_scores) if cyb_scores else 50

        X = []; init_scores = []
        for h in horses:
            ent = entries.get(h, {})
            idm = ent.get('idm') or 50; rider = ent.get('rider') or 0
            jn = ent.get('jockey',''); tn = ent.get('trainer','')
            f = {}
            f['idm_c'] = idm - avg_idm; f['rider_c'] = rider - avg_rider
            f['total_index'] = ent.get('total') or 0
            oz_p = oz_inv.get(h,0)/oz_sum; mk_p = mk_inv.get(h,0)/mk_sum
            f['expert_resid'] = math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
            f['cyb_c'] = cyb.get(h,0) - avg_cyb
            js = self.stats['jockey_stats'].get(jn, {})
            f['jockey_t3rate'] = js.get('t3',0)/js['r'] if js.get('r',0)>=30 else -1
            ts = self.stats['trainer_stats'].get(tn, {})
            f['trainer_t3rate'] = ts.get('t3',0)/ts['r'] if ts.get('r',0)>=30 else -1
            hid = ent.get('hid','')
            runs = self.stats['horse_history'].get(hid, [])
            f['horse_runs'] = len(runs)
            if runs:
                rc = runs[-5:]
                f['avg_fp_5'] = np.mean([r['fp'] for r in rc])
                f['top3_rate'] = sum(1 for r in runs if r['fp']<=3)/len(runs)
                f['last_fp'] = runs[-1]['fp']
                dr = [r for r in runs if abs(r.get('dist',0)-dt)<=200]
                f['dist_t3rate'] = sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
                sr = [r for r in runs if r.get('surface')==sf]
                f['surf_t3rate'] = sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
                f['trend'] = runs[-3]['fp']-runs[-1]['fp'] if len(runs)>=3 else 0
                f['win_rate'] = sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
            else:
                f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'dist_t3rate':-1,'surf_t3rate':-1,'trend':0,'win_rate':-1})
            f['nhead'] = n; f['distance'] = dt; f['surface'] = sf_map.get(sf,0)
            f['track_cond'] = tc_map.get(tc,0); f['grade'] = grade_map.get(grade,0)
            f['is_senkou'] = 1 if ent.get('run_style','') in ('逃げ','先行') else 0
            f['gate_ratio'] = h/n
            cw = ent.get('weight') or 0
            avg_cw = np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in horses])
            f['weight_c'] = (cw-avg_cw) if cw>0 else 0
            # move_5to1
            o5 = odds_5min.get(h,0); o1 = odds_1min.get(h,0)
            f['move_5to1'] = (o5-o1)/o5 if o5>0 and o1>0 else 0

            X.append([f.get(k,0) for k in self.feature_names])
            p = mp.get(h, 1/n)
            init_scores.append(math.log(max(p,1e-15))-math.log(max(1-p,1e-15)))

        return np.array(X, dtype=np.float32), np.array(init_scores, dtype=np.float64)

    def predict(self, X, init_scores, odds_1min, horses):
        """EV計算して投票判断"""
        raw = self.model.predict(X, raw_score=True)
        s = self.b * init_scores + self.tau * raw
        s -= s.max()
        probs = np.exp(s) / np.exp(s).sum()

        results = []
        for i, h in enumerate(horses):
            ev = probs[i] * odds_1min.get(h, 0)
            results.append({
                'horse_number': h,
                'model_prob': float(probs[i]),
                'odds_1min': odds_1min.get(h, 0),
                'ev': float(ev),
                'bet': ev >= self.ev_threshold
            })
        return sorted(results, key=lambda x: -x['ev'])

# === Main runner ===
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['paper', 'live', 'ask'], default='ask',
                        help='paper=ペーパーのみ, live=全自動投票, ask=レースごとに確認(デフォルト)')
    args = parser.parse_args()

    mode = args.mode.upper()
    print(f'=== 競馬AI リアルタイムエンジン ({mode}) ===')
    print(f'  {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    if mode == 'ASK':
        print(f'  ※ 投票候補があるレースごとに [実投票/ペーパー/スキップ] を選べます')

    # Load model
    engine = PredictionEngine()

    # Initialize voters (both ready for ASK mode)
    from ipat_voter import IPATVoter, PaperTrader
    paper_trader = PaperTrader()
    live_voter = None
    if mode == 'LIVE':
        live_voter = IPATVoter(headless=False)
        live_voter.login()

    # For mode selection
    def get_voter_for_race(mode, bets_info):
        """レースごとにペーパー/実投票を選択"""
        nonlocal live_voter
        if mode == 'PAPER':
            return paper_trader
        if mode == 'LIVE':
            return live_voter
        # ASK mode
        print(f'\n  投票候補: {len(bets_info)}件')
        for b in bets_info:
            print(f'    馬番{b["horse_number"]:>2} odds={b["odds_1min"]:>6.1f} EV={b["ev"]:.3f}')
        while True:
            choice = input(f'  → [L]実投票 / [P]ペーパー / [S]スキップ: ').strip().upper()
            if choice in ('L', 'LIVE'):
                if live_voter is None:
                    live_voter = IPATVoter(headless=False)
                    live_voter.login()
                return live_voter
            elif choice in ('P', 'PAPER', ''):
                return paper_trader
            elif choice in ('S', 'SKIP'):
                return None
            print(f'    L/P/S を入力してください')

    # Get today's races
    db = sqlite3.connect(DB_PATH)
    today = datetime.now().strftime('%Y-%m-%d')
    races = db.execute(
        'SELECT race_id, race_date, start_time, venue_name, race_number, surface, distance, track_condition, grade '
        'FROM races WHERE race_date = ? ORDER BY start_time', (today,)
    ).fetchall()
    db.close()

    if not races:
        print(f'\n  今日({today})のレースがありません。')
        return

    print(f'\n  今日のレース: {len(races)}件')

    # Process each race
    jv = create_jv()
    daily_log = []

    for race in races:
        rid, rd, st, venue, rnum, sf, dist, tc, grade = race
        if not st: continue

        h, m = int(st.split(':')[0]), int(st.split(':')[1])
        start_dt = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
        now = datetime.now()

        if start_dt < now - timedelta(minutes=5):
            continue  # Already past

        # Convert to JRA-VAN key
        try:
            race_key = jrdb_to_jravan_key(rid, rd)
        except:
            continue

        race_info = {
            'race_id': rid, 'venue': venue, 'race_number': rnum,
            'surface': sf, 'distance': dist, 'track_condition': tc, 'grade': grade
        }

        print(f'\n{"="*60}')
        print(f'  {venue} {rnum}R {st} | {sf}{dist}m {tc} | rid={rid}')
        print(f'{"="*60}')

        # Wait until 5 minutes before
        wait_until = start_dt - timedelta(minutes=5)
        wait_sec = (wait_until - datetime.now()).total_seconds()
        if wait_sec > 0:
            print(f'  発走5分前まで {wait_sec:.0f}秒待機...')
            while datetime.now() < wait_until:
                remaining = (wait_until - datetime.now()).total_seconds()
                if remaining > 60:
                    time.sleep(30)
                elif remaining > 10:
                    time.sleep(5)
                else:
                    time.sleep(max(0, remaining))
                    break

        # === 5分前オッズ取得 ===
        print(f'  [{datetime.now().strftime("%H:%M:%S")}] 5分前オッズ取得...')
        odds_5min = fetch_realtime_win_odds(jv, race_key)
        print(f'    → {len(odds_5min)} horses')

        # Wait until 1 minute before
        wait_until = start_dt - timedelta(seconds=60)
        wait_sec = (wait_until - datetime.now()).total_seconds()
        if wait_sec > 0:
            print(f'  1分前まで {wait_sec:.0f}秒待機...')
            time.sleep(max(0, wait_sec))

        # === 1分前オッズ取得 ===
        print(f'  [{datetime.now().strftime("%H:%M:%S")}] 1分前オッズ取得...')
        odds_1min = fetch_realtime_win_odds(jv, race_key)
        print(f'    → {len(odds_1min)} horses')

        if not odds_1min or len(odds_1min) < 5:
            print(f'  [SKIP] オッズ取得失敗')
            continue

        # === 30秒前オッズ取得 ===
        wait_until = start_dt - timedelta(seconds=30)
        wait_sec = (wait_until - datetime.now()).total_seconds()
        if wait_sec > 0:
            time.sleep(max(0, wait_sec))
        print(f'  [{datetime.now().strftime("%H:%M:%S")}] 30秒前オッズ取得...')
        odds_30sec = fetch_realtime_win_odds(jv, race_key)

        # === 予測 ===
        horses = sorted(odds_1min.keys())
        try:
            X, init_scores = engine.build_features(race_info, horses, odds_1min, odds_5min)
            predictions = engine.predict(X, init_scores, odds_1min, horses)
        except Exception as e:
            print(f'  [ERROR] 予測失敗: {e}')
            continue

        # === 結果表示 ===
        bets = [p for p in predictions if p['bet']]
        print(f'\n  予測結果:')
        for p in predictions[:5]:
            mark = '★BET' if p['bet'] else ''
            print(f'    hn={p["horse_number"]:>2} odds={p["odds_1min"]:>6.1f} prob={p["model_prob"]:.3f} EV={p["ev"]:.3f} {mark}')
        if bets:
            print(f'\n  → {len(bets)}件の投票候補 (EV≥{engine.ev_threshold})')
        else:
            print(f'\n  → 投票候補なし')

        # === 記録 ===
        race_log = {
            'race_id': rid, 'venue': venue, 'race_number': rnum,
            'start_time': st, 'surface': sf, 'distance': dist,
            'timestamp': datetime.now().isoformat(),
            'odds_5min': {str(k):v for k,v in odds_5min.items()},
            'odds_1min': {str(k):v for k,v in odds_1min.items()},
            'odds_30sec': {str(k):v for k,v in odds_30sec.items()},
            'predictions': predictions,
            'bets': bets,
            'mode': mode
        }
        daily_log.append(race_log)

        # === 投票実行 ===
        if bets:
            voter = get_voter_for_race(mode, bets)
            if voter is None:
                print(f'  [SKIP] ユーザーがスキップ')
                race_log['skipped'] = True
            else:
                venue_code = None
                db2 = sqlite3.connect(DB_PATH)
                vc_row = db2.execute('SELECT venue_code FROM races WHERE race_id=?', (rid,)).fetchone()
                if vc_row: venue_code = vc_row[0]
                db2.close()

                max_bets = voter.max_bet_per_race if hasattr(voter, 'max_bet_per_race') else 1
                for bet in bets[:max_bets]:
                    if venue_code:
                        success, status = voter.place_bet(
                            venue_code=venue_code,
                            race_number=rnum,
                            horse_number=bet['horse_number'],
                            amount=voter.bet_amount if hasattr(voter, 'bet_amount') else 100,
                            bet_type='win',
                            ev=bet['ev'],
                            model_prob=bet['model_prob'],
                            odds_1min=bet['odds_1min']
                        )
                        bet['vote_status'] = status

    # Save daily log
    log_path = os.path.join(LOG_DIR, f'log_{today}.json')
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(daily_log, f, ensure_ascii=False, indent=2)
    print(f'\n  ログ保存: {log_path}')

    try: jv.JVClose()
    except: pass
    paper_trader.close()
    if live_voter: live_voter.close()

    # Summary
    total_bets = sum(len(r['bets']) for r in daily_log)
    print(f'\n=== 本日のサマリー ===')
    print(f'  処理レース: {len(daily_log)}')
    print(f'  投票候補: {total_bets}件')
    print(f'  モード: {mode}')
    print(f'\nDone!')

if __name__ == '__main__':
    main()
