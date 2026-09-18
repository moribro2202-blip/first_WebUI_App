# -*- coding: utf-8 -*-
"""リアルタイム予測・投票エンジン（32bit Python専用）
レース発走前に自動で:
  1. 馬体重取得（10分前）
  2. オッズ監視（3分前〜1分前）
  3. モデル予測 × 直前オッズ → 妙味馬判定
  4. 投票推奨出力（JSON）

使い方: py -3.12-32 scripts/jravan/realtime_engine.py [--race YYYYMMDDVVKKHHRR]
        py -3.12-32 scripts/jravan/realtime_engine.py --today
"""
import json, os, sys, time, math, argparse, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
OUTPUT_DIR = os.path.join(BASE, 'data', 'realtime_output')
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ============================================================
# JV-Link Wrapper
# ============================================================
class JVLink:
    def __init__(self):
        import win32com.client
        self.jv = win32com.client.Dispatch('JVDTLab.JVLink')
        ret = self.jv.JVInit('UNKNOWN')
        if ret != 0:
            raise RuntimeError(f'JVInit failed: {ret}')

    def get_realtime_odds(self, race_key):
        """直前単勝オッズを取得（0B31=単勝・複勝オッズ）"""
        ret = self.jv.JVRTOpen('0B31', race_key)
        records = []
        for _ in range(1000):
            try:
                r = self.jv.JVRead(bytearray(200000), 200000, '')
                if isinstance(r, tuple) and len(r) >= 2:
                    rc = r[0]
                    if rc == 0: break
                    if rc == -1: continue
                    if rc > 0 and r[1]:
                        records.append(r[1])
                else:
                    break
            except:
                break
        try: self.jv.JVClose()
        except: pass
        return records

    def get_horse_weight(self, race_key):
        """馬体重を取得（WH spec）"""
        ret = self.jv.JVRTOpen('0B15', race_key)
        records = []
        for _ in range(100):
            try:
                r = self.jv.JVRead(bytearray(200000), 200000, '')
                if isinstance(r, tuple) and len(r) >= 2:
                    rc = r[0]
                    if rc == 0: break
                    if rc == -1: continue
                    if rc > 0 and r[1]:
                        records.append(r[1])
                else:
                    break
            except:
                break
        try: self.jv.JVClose()
        except: pass
        return records

    def get_todays_races(self):
        """本日のレース一覧を取得"""
        today = datetime.now().strftime('%Y%m%d')
        ret = self.jv.JVOpen('RACE', f'{today}000000', 2, 0, 0, '')
        races = []
        if isinstance(ret, tuple) and ret[0] >= 0:
            needed = ret[2] if len(ret) > 2 else 0
            if needed > 0:
                t0 = time.time()
                while self.jv.JVStatus() < needed:
                    if time.time() - t0 > 30: break
                    time.sleep(0.3)
            for _ in range(50000):
                r = self.jv.JVRead(bytearray(200000), 200000, '')
                if isinstance(r, tuple) and len(r) >= 2:
                    rc = r[0]
                    if rc == 0: break
                    if rc == -1: continue
                    if rc > 0 and r[1]:
                        data = r[1]
                        if data[:2] == 'RA' and len(data) >= 27:
                            race_key = data[11:27]
                            races.append(race_key)
                else:
                    break
        try: self.jv.JVClose()
        except: pass
        return races

    def close(self):
        try: self.jv.JVClose()
        except: pass

# ============================================================
# Odds Parser
# ============================================================
def parse_win_odds_from_o1(record):
    """O1/直前オッズレコードから単勝オッズをパース"""
    s = record if isinstance(record, str) else str(record)
    if len(s) < 43: return {}
    try:
        nhead = int(s[35:37])
    except:
        return {}
    horses = {}
    for i in range(min(nhead, 18)):
        pos = 43 + i * 8
        if pos + 8 > len(s): break
        try:
            hno = int(s[pos:pos+2])
            odds = int(s[pos+2:pos+6]) / 10.0
            pop = int(s[pos+6:pos+8])
            if hno > 0 and odds > 0:
                horses[hno] = {'odds': odds, 'pop': pop}
        except:
            pass
    return horses

# ============================================================
# Model Predictor
# ============================================================
class ModelPredictor:
    def __init__(self):
        self.db = sqlite3.connect(DB_PATH)
        self._load_caches()
        self._load_model()

    def _load_caches(self):
        """DB からキャッシュをロード"""
        self.entry_cache = {}
        for rid, in self.db.execute('SELECT DISTINCT race_id FROM entries').fetchall():
            es = self.db.execute('SELECT horse_number,horse_id,jockey_name,idm,total_index,rider_index,run_style FROM entries WHERE race_id=?',(rid,)).fetchall()
            if es: self.entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'idm':e[3],'total':e[4],'rider':e[5],'run_style':e[6]} for e in es}

        self.race_cond = {r[0]:r[1] for r in self.db.execute('SELECT race_id,track_condition FROM races').fetchall()}
        self.race_grade = {r[0]:r[1] for r in self.db.execute('SELECT race_id,grade FROM races').fetchall()}

        # Historical stats (pre-built)
        self.jockey_stats = defaultdict(lambda: {'r':0,'w':0,'t3':0})
        self.horse_hist = defaultdict(list)
        self.horse_track = defaultdict(lambda: defaultdict(list))

        # Build from results
        for row in self.db.execute('SELECT r.race_id,r.race_date,rc.surface,rc.distance,rc.venue_code,res.horse_number,res.finish_position,res.horse_id,res.horse_weight_diff FROM results res JOIN races rc ON res.race_id=rc.race_id JOIN races r ON res.race_id=r.race_id WHERE res.finish_position IS NOT NULL ORDER BY r.race_date,r.race_id').fetchall():
            rid,rd,sf,dt,vc,hn,fp,hid,wd = row
            ent = self.entry_cache.get(rid,{}).get(hn,{})
            jn = ent.get('jockey','')
            tc = self.race_cond.get(rid,'良')
            if jn:
                self.jockey_stats[jn]['r'] += 1
                if fp == 1: self.jockey_stats[jn]['w'] += 1
                if fp <= 3: self.jockey_stats[jn]['t3'] += 1
            if hid:
                self.horse_hist[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'wd':wd})
                if len(self.horse_hist[hid]) > 30:
                    self.horse_hist[hid] = self.horse_hist[hid][-30:]
                if tc:
                    self.horse_track[hid][tc].append(fp)

        print(f"  Caches: {len(self.jockey_stats)} jockeys, {len(self.horse_hist)} horses")

    def _load_model(self):
        """学習済みモデルをロード（なければ学習）"""
        import lightgbm as lgb
        model_path = os.path.join(MODEL_DIR, 'v5_latest.txt')
        if os.path.exists(model_path):
            self.model = lgb.Booster(model_file=model_path)
            self.feature_names = self.model.feature_name()
            print(f"  Model loaded: {model_path}")
        else:
            print("  No pre-trained model found. Train first with model_v5_combined.py")
            self.model = None
            self.feature_names = None

    def predict_race(self, race_id, realtime_odds=None):
        """1レースの全馬の予測確率を返す"""
        if self.model is None:
            return {}

        entries = self.entry_cache.get(race_id, {})
        race_info = self.db.execute('SELECT venue_code,surface,distance FROM races WHERE race_id=?',(race_id,)).fetchone()
        if not race_info or not entries:
            return {}

        vc, sf, dt = race_info
        hl = sorted(entries.keys())
        if len(hl) < 5:
            return {}

        grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
        tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
        sf_map = {'芝':0,'ダート':1}

        tc = self.race_cond.get(race_id, '良')
        grade = self.race_grade.get(race_id) or '一般'
        nhead = len(hl)
        ai = [entries.get(h,{}).get('idm') or 0 for h in hl]
        avg_i = sum(ai)/len(ai); mx_i = max(ai)
        std_i = (sum((x-avg_i)**2 for x in ai)/len(ai))**0.5 if ai else 0
        ar = [entries.get(h,{}).get('rider') or 0 for h in hl]
        avg_r = sum(ar)/len(ar)

        # Market probability from realtime odds
        if realtime_odds:
            rt_inv = {h: 1/realtime_odds[h]['odds'] for h in realtime_odds if realtime_odds[h]['odds'] > 0}
            rt_sum = sum(rt_inv.values()) if rt_inv else 1
        else:
            rt_inv = {}; rt_sum = 1

        results = {}
        feature_rows = []
        horse_list = []

        for h in hl:
            ent = entries.get(h, {})
            hid = ent.get('hid', '')
            idm = ent.get('idm') or 0
            rider = ent.get('rider') or 0

            f = {}
            f['idm'] = idm; f['rider_index'] = rider; f['total_index'] = ent.get('total') or 0
            f['idm_vs_field'] = idm - avg_i; f['idm_vs_max'] = idm - mx_i
            f['idm_zscore'] = (idm - avg_i) / std_i if std_i > 0 else 0
            f['rider_vs_field'] = rider - avg_r; f['combined_index'] = idm + rider
            f['nhead'] = nhead; f['distance'] = dt; f['surface'] = sf_map.get(sf, 0)
            f['grade'] = grade_map.get(grade, 0); f['track_cond'] = tc_map.get(tc, 0)
            f['is_senkou'] = 1 if ent.get('run_style', '') in ('逃げ','先行') else 0

            # Jockey
            jn = ent.get('jockey', '')
            js = self.jockey_stats.get(jn, {})
            jr = js.get('r', 0)
            f['jockey_winrate'] = js.get('w',0)/jr if jr >= 30 else -1
            f['jockey_top3rate'] = js.get('t3',0)/jr if jr >= 30 else -1
            f['jockey_venue_t3rate'] = -1  # simplified

            # Horse history
            hist = self.horse_hist.get(hid, [])
            f['horse_runs'] = len(hist)
            if hist:
                rc = hist[-5:]
                f['avg_fp_5'] = sum(r['fp'] for r in rc)/len(rc)
                f['best_fp_5'] = min(r['fp'] for r in rc)
                f['top3_rate'] = sum(1 for r in hist if r['fp']<=3)/len(hist)
                f['last_fp'] = hist[-1]['fp']
                dr = [r for r in hist if r.get('dist') and abs(r['dist']-dt)<=200]
                f['dist_top3rate'] = sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
                sr = [r for r in hist if r.get('surface')==sf]
                f['surf_top3rate'] = sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
                f['trend'] = hist[-3]['fp']-hist[-1]['fp'] if len(hist)>=3 else 0
                wd = [r.get('wd') for r in hist[-3:] if r.get('wd') is not None]
                f['abs_wd'] = abs(wd[-1]) if wd else 0
            else:
                f.update({'avg_fp_5':8,'best_fp_5':8,'top3_rate':0,'last_fp':8,
                          'dist_top3rate':-1,'surf_top3rate':-1,'trend':0,'abs_wd':0})
            tch = self.horse_track.get(hid,{}).get(tc,[])
            f['track_top3rate'] = sum(1 for x in tch if x<=3)/len(tch) if tch else -1

            # Realtime odds features
            if realtime_odds and h in realtime_odds:
                rt_odds = realtime_odds[h]['odds']
                f['ts5_log'] = math.log(max(rt_odds, 1))
                f['ts5_market_p'] = rt_inv.get(h, 0) / rt_sum if rt_sum > 0 else 0
                f['ts5_rank'] = realtime_odds[h].get('pop', 0)
            else:
                f['ts5_log'] = -1; f['ts5_market_p'] = -1; f['ts5_rank'] = -1

            # Placeholder for features we don't have in realtime
            for k in ['cyb_grade','cyb_score','cyb_vs_field','expert_disagree',
                       'expert_edge','expert_vs_ts5','has_cyb','odds_accel',
                       'odds_move_15to5','odds_move_30to5','oz_expert_p','sed_market_p']:
                if k not in f:
                    f[k] = -1

            horse_list.append(h)
            feature_rows.append([f.get(k, 0) for k in self.feature_names])

        if not feature_rows:
            return {}

        import numpy as np
        X = np.array(feature_rows)
        probs = self.model.predict(X)

        for i, h in enumerate(horse_list):
            market_p = rt_inv.get(h, 0) / rt_sum if rt_sum > 0 and h in rt_inv else 0
            model_p = probs[i]
            edge = model_p / market_p if market_p > 0 else 0
            results[h] = {
                'model_p': float(model_p),
                'market_p': float(market_p),
                'edge': float(edge),
                'odds': realtime_odds.get(h, {}).get('odds', 0) if realtime_odds else 0,
                'pop': realtime_odds.get(h, {}).get('pop', 0) if realtime_odds else 0,
            }

        return results

    def close(self):
        self.db.close()

# ============================================================
# Race Monitor
# ============================================================
def monitor_race(jv, predictor, race_key, jrdb_rid):
    """1レースの監視・予測・推奨"""
    print(f'\n{"="*60}')
    print(f'  レース: {race_key} (JRDB: {jrdb_rid})')
    print(f'{"="*60}')

    # Get realtime odds
    print("  オッズ取得中...", flush=True)
    records = jv.get_realtime_odds(race_key)
    if not records:
        print("  オッズ取得失敗")
        return None

    # Parse latest odds
    latest_odds = None
    for rec in reversed(records):
        parsed = parse_win_odds_from_o1(rec)
        if parsed:
            latest_odds = parsed
            break

    if not latest_odds:
        print("  オッズパース失敗")
        return None

    print(f"  {len(latest_odds)}頭のオッズ取得")

    # Model prediction
    predictions = predictor.predict_race(jrdb_rid, latest_odds)
    if not predictions:
        print("  予測失敗")
        return None

    # Rank by edge
    ranked = sorted(predictions.items(), key=lambda x: -x[1]['edge'])

    # Display
    print(f'\n  {"馬番":>4} {"オッズ":>7} {"人気":>4} {"モデルP":>7} {"市場P":>7} {"エッジ":>6} {"判定"}')
    print(f'  {"-"*55}')
    recommendations = []
    for h, pred in ranked:
        odds = pred['odds']
        pop = pred['pop']
        mp = pred['model_p']
        mkp = pred['market_p']
        edge = pred['edge']

        # 妙味判定
        if edge >= 1.3 and mp >= 0.15:
            verdict = '★★★ 強推奨'
        elif edge >= 1.1 and mp >= 0.10:
            verdict = '★★ 推奨'
        elif edge >= 1.0:
            verdict = '★ 候補'
        else:
            verdict = ''

        if verdict:
            recommendations.append({'horse': h, 'edge': edge, 'odds': odds, 'verdict': verdict})

        print(f'  {h:>4} {odds:>6.1f}x {pop:>4} {mp:>6.1%} {mkp:>6.1%} {edge:>5.2f}x {verdict}')

    # Output JSON
    output = {
        'race_key': race_key,
        'jrdb_rid': jrdb_rid,
        'timestamp': datetime.now().isoformat(),
        'odds': {str(h): {'odds': d['odds'], 'pop': d['pop']} for h, d in latest_odds.items()},
        'predictions': {str(h): pred for h, pred in predictions.items()},
        'recommendations': recommendations,
    }

    out_path = os.path.join(OUTPUT_DIR, f'rec_{race_key}.json')
    json.dump(output, open(out_path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print(f'\n  推奨出力: {out_path}')
    print(f'  推奨馬: {len(recommendations)}頭')

    return output

# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--race', help='16桁レースキー')
    parser.add_argument('--today', action='store_true', help='本日の全レースを監視')
    parser.add_argument('--test', action='store_true', help='テストモード（最近のレースで検証）')
    args = parser.parse_args()

    print("=== リアルタイム予測エンジン ===")

    # Load model
    print("モデルロード中...")
    predictor = ModelPredictor()

    if args.test:
        # Test with recent race from DB
        db = sqlite3.connect(DB_PATH)
        recent = db.execute('SELECT race_id, race_date FROM races ORDER BY race_date DESC LIMIT 1').fetchone()
        db.close()
        if recent:
            print(f"テストレース: {recent[0]} ({recent[1]})")
            # Use stored TS odds as proxy for realtime
            db2 = sqlite3.connect(DB_PATH)
            ts_odds = {}
            for hn, odds, pop in db2.execute('SELECT horse_number, odds, popularity FROM ts_win_odds WHERE race_id=? AND minutes_before=1',(recent[0],)).fetchall():
                ts_odds[hn] = {'odds': odds, 'pop': pop}
            db2.close()

            if ts_odds:
                predictions = predictor.predict_race(recent[0], ts_odds)
                if predictions:
                    ranked = sorted(predictions.items(), key=lambda x: -x[1]['edge'])
                    print(f'\n  {"馬番":>4} {"オッズ":>7} {"モデルP":>7} {"市場P":>7} {"エッジ":>6}')
                    print(f'  {"-"*40}')
                    for h, pred in ranked[:10]:
                        print(f'  {h:>4} {pred["odds"]:>6.1f}x {pred["model_p"]:>6.1%} {pred["market_p"]:>6.1%} {pred["edge"]:>5.2f}x')
        return

    if args.race:
        jv = JVLink()
        # Convert race key to JRDB rid (approximate)
        key = args.race
        yy = key[2:4]; vv = key[8:10]
        kai = int(key[10:12]); day = int(key[12:14]); rr = int(key[14:16])
        day_hex = format(day, 'x')
        jrdb_rid = f'{yy}{vv}{kai}{day_hex}{rr:02d}'

        monitor_race(jv, predictor, key, jrdb_rid)
        jv.close()
        return

    if args.today:
        print("本日のレース取得中...")
        jv = JVLink()
        races = jv.get_todays_races()
        print(f"本日: {len(races)}レース")
        for race_key in sorted(races):
            yy = race_key[2:4]; vv = race_key[8:10]
            kai = int(race_key[10:12]); day = int(race_key[12:14]); rr = int(race_key[14:16])
            day_hex = format(day, 'x')
            jrdb_rid = f'{yy}{vv}{kai}{day_hex}{rr:02d}'
            monitor_race(jv, predictor, race_key, jrdb_rid)
        jv.close()
        return

    print("使い方: --race XXXXXXXXXXXXXXXX / --today / --test")

if __name__ == '__main__':
    main()
