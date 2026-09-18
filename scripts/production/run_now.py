# -*- coding: utf-8 -*-
"""即実行: オッズ取得 → モデル予測 → 最高EV馬券を特定 → 投票直前まで
python scripts/production/run_now.py
python scripts/production/run_now.py --execute  # 実際に投票
"""
import os, sys, json, math, time, sqlite3, argparse
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
MODEL_DIR = os.path.join(BASE, 'data', 'models')

from ipat_voter import IPATVoter

parser = argparse.ArgumentParser()
parser.add_argument('--execute', action='store_true', help='実際に投票する（デフォルトは確認のみ）')
parser.add_argument('--headless', action='store_true', help='ブラウザ非表示')
args = parser.parse_args()

# ============================================================
# 1. 即PATログイン + 開催情報取得
# ============================================================
print("=" * 60)
print("=== 即実行モード ===")
print("=" * 60)

voter = IPATVoter(headless=args.headless)
if not voter.login():
    print("ログイン失敗")
    voter.close()
    sys.exit(1)

print("\n--- 開催情報取得 ---")
venues_info = voter.get_venues_and_races()
if not venues_info:
    print("開催情報取得失敗")
    voter.close()
    sys.exit(1)

# 当日開催のみ（土 or 日）
from datetime import datetime, timedelta
import calendar
weekday = datetime.now().weekday()  # 0=Mon ... 6=Sun
day_char = '日' if weekday == 6 else '土'
today_venues = [v for v in venues_info if v['day'] == day_char]
if not today_venues:
    # 当日が平日 or 該当なし → 全部対象
    today_venues = venues_info
    print(f"  当日開催判定: 全開催対象 ({len(today_venues)}場)")
else:
    names = ', '.join(f"{v['venue']}（{v['day']}）" for v in today_venues)
    print(f"  当日開催: {names}")

# ============================================================
# 2. 全レースのオッズ取得
# ============================================================
print("\n--- オッズ取得 ---")
all_race_odds = {}  # {(venue, race_num): {horse_num: odds}}
for vi in today_venues:
    venue = vi['venue']
    odds_by_race = voter.get_all_odds(venue)
    if odds_by_race:
        for rnum, odds in odds_by_race.items():
            all_race_odds[(venue, rnum)] = odds

print(f"\n  取得レース数: {len(all_race_odds)}")
if not all_race_odds:
    print("オッズ取得失敗")
    voter.close()
    sys.exit(1)

# ============================================================
# 3. モデルロード
# ============================================================
print("\n--- モデルロード ---")
config_path = os.path.join(MODEL_DIR, 'prod_config.json')
model = None

if not os.path.exists(config_path):
    print(f"  prod_config.json がありません。")
    print(f"  モデルなしでオッズのみ表示します。")
else:
    import lightgbm as lgb
    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    model_path = os.path.join(MODEL_DIR, config['model_file'])
    model = lgb.Booster(model_file=model_path)
    feature_names = config['feature_names']
    b_param = config['b']
    tau_param = config['tau']
    beta = config['beta']
    ev_threshold = config['ev_threshold']

    stats_path = os.path.join(MODEL_DIR, config['stats_file'])
    with open(stats_path, 'r', encoding='utf-8') as f:
        stats = json.load(f)

    print(f"  b={b_param:.4f}, τ={tau_param:.4f}, EV閾値={ev_threshold}")

# ============================================================
# 4. 予測 (モデルがある場合)
# ============================================================
all_predictions = []
venue_code_map = {
    '札幌':'01','函館':'02','福島':'03','新潟':'04','東京':'05',
    '中山':'06','中京':'07','京都':'08','阪神':'09','小倉':'10'
}

if model is not None:
    print("\n--- 予測 ---")
    db = sqlite3.connect(DB_PATH)

    candidates = [(datetime.now() + timedelta(days=d)).strftime('%Y-%m-%d') for d in range(0, 3)]

    grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
    tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
    sf_map = {'芝':0,'ダート':1}

    for (venue, rnum), odds in all_race_odds.items():
        vc = venue_code_map.get(venue, '')
        if not vc:
            continue

        # DBからレースを探す
        race_row = None
        for dt in candidates:
            rows = db.execute(
                'SELECT race_id, race_date, surface, distance, track_condition, grade, start_time '
                'FROM races WHERE venue_code=? AND race_number=? AND race_date>=? ORDER BY race_date LIMIT 1',
                (vc, rnum, candidates[0])
            ).fetchall()
            if rows:
                race_row = rows[0]
                break

        if not race_row:
            print(f"\n  {venue} {rnum}R: DB未登録（JRDBインポートが必要）")
            for hn in sorted(odds.keys()):
                print(f"    馬番{hn:>2}: {odds[hn]:>6.1f}倍")
            continue

        rid, rd, sf, dist, tc, grade, st = race_row

        # エントリー取得
        entries = {}
        for row in db.execute(
            'SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight '
            'FROM entries WHERE race_id=?', (rid,)
        ).fetchall():
            entries[row[0]] = {'hid':row[1],'jockey':row[2],'trainer':row[3],'idm':row[4],
                               'total':row[5],'rider':row[6],'run_style':row[7],'weight':row[8]}

        if not entries:
            print(f"\n  {venue} {rnum}R: エントリーデータなし")
            continue

        horses = sorted(entries.keys())
        n = len(horses)
        if n < 5:
            continue

        # 市場確率（即PATオッズから）
        inv = np.array([1/odds.get(h, 999) for h in horses])
        mp = inv / inv.sum()
        mp = mp ** beta
        mp = mp / mp.sum()

        # 前日オッズ
        oz = {}
        for row in db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall():
            try: oz[int(row[0])] = row[1]
            except: pass
        oz_inv = {h: 1/oz[h] if h in oz and oz[h]>0 else 0 for h in horses}
        mk_inv = {h: 1/odds.get(h, 999) for h in horses}
        oz_sum = sum(oz_inv.values()) or 1
        mk_sum = sum(mk_inv.values()) or 1

        # 統計情報
        idms = [entries.get(h,{}).get('idm') or 50 for h in horses]
        avg_idm = np.mean(idms)
        riders = [entries.get(h,{}).get('rider') or 0 for h in horses]
        avg_rider = np.mean(riders)

        # 特徴量構築
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
            oz_p = oz_inv.get(h,0)/oz_sum
            mk_p = mk_inv.get(h,0)/mk_sum
            f['expert_resid'] = math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0

            js = stats.get('jockey_stats', {}).get(jn, {})
            f['jockey_t3rate'] = js.get('t3',0)/js['r'] if js.get('r',0)>=30 else -1
            ts = stats.get('trainer_stats', {}).get(tn, {})
            f['trainer_t3rate'] = ts.get('t3',0)/ts['r'] if ts.get('r',0)>=30 else -1

            runs = stats.get('horse_history', {}).get(hid, [])
            f['horse_runs'] = len(runs)
            if runs:
                rc = runs[-5:]
                f['avg_fp_5'] = np.mean([r['fp'] for r in rc])
                f['top3_rate'] = sum(1 for r in runs if r['fp']<=3)/len(runs)
                f['last_fp'] = runs[-1]['fp']
                dr = [r for r in runs if abs(r.get('dist',0)-dist)<=200]
                f['dist_t3rate'] = sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
                sr = [r for r in runs if r.get('surface')==sf]
                f['surf_t3rate'] = sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
                f['trend'] = runs[-3]['fp']-runs[-1]['fp'] if len(runs)>=3 else 0
                f['win_rate'] = sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
            else:
                f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'dist_t3rate':-1,
                          'surf_t3rate':-1,'trend':0,'win_rate':-1})

            f['nhead'] = n
            f['distance'] = dist
            f['surface'] = sf_map.get(sf, 0)
            f['track_cond'] = tc_map.get(tc or '良', 0)
            f['grade'] = grade_map.get(grade or '一般', 0)
            f['is_senkou'] = 1 if ent.get('run_style','') in ('逃げ','先行') else 0
            f['gate_ratio'] = h / n
            cw = ent.get('weight') or 0
            avg_cw = np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in horses])
            f['weight_c'] = (cw - avg_cw) if cw > 0 else 0
            f['move_5to1'] = 0  # リアルタイムでは未取得

            X.append([f.get(k, 0) for k in feature_names])
            p = mp[i]
            init_scores.append(math.log(max(p, 1e-15)) - math.log(max(1-p, 1e-15)))

        X = np.array(X, dtype=np.float32)
        init_scores = np.array(init_scores, dtype=np.float64)

        # 予測
        raw = model.predict(X, raw_score=True)
        s = b_param * init_scores + tau_param * raw
        s -= s.max()
        probs = np.exp(s) / np.exp(s).sum()

        # EV計算
        race_results = []
        for i, h in enumerate(horses):
            o = odds.get(h, 0)
            ev_val = probs[i] * o if o > 0 else 0
            race_results.append({
                'venue': venue, 'race_number': rnum, 'horse_number': h,
                'odds': o, 'model_prob': float(probs[i]), 'ev': float(ev_val),
                'surface': sf, 'distance': dist, 'start_time': st,
                'venue_code': vc, 'race_id': rid,
            })

        race_results.sort(key=lambda x: -x['ev'])

        # 表示
        print(f"\n  {venue} {rnum}R ({sf}{dist}m {tc or '良'}) 発走{st or '?'}")
        print(f"  {'馬番':>4} {'オッズ':>7} {'モデルP':>7} {'EV':>6} {'判定'}")
        print(f"  {'-'*40}")
        for r in race_results[:8]:
            mark = ' ★BET' if r['ev'] >= ev_threshold else ''
            print(f"  {r['horse_number']:>4} {r['odds']:>6.1f}x {r['model_prob']:>6.3f} {r['ev']:>5.2f}{mark}")

        # EV閾値以上を候補に追加
        for r in race_results:
            if r['ev'] >= ev_threshold:
                all_predictions.append(r)

    db.close()

else:
    # モデルなし → オッズのみ表示
    print("\n--- オッズ一覧（モデルなし）---")
    for (venue, rnum), odds in sorted(all_race_odds.items()):
        print(f"\n  {venue} {rnum}R:")
        for hn in sorted(odds.keys()):
            print(f"    馬番{hn:>2}: {odds[hn]:>6.1f}倍")

# ============================================================
# 5. 最高EV馬券を特定
# ============================================================
print(f"\n{'='*60}")
if model:
    print(f"=== 投票候補（EV >= {ev_threshold}）===")
else:
    print(f"=== オッズ取得完了（モデルなし）===")
print(f"{'='*60}")

if not all_predictions:
    print("  投票候補なし")
    if not args.headless:
        print("\n  ブラウザを確認してください。Enterキーで終了...")
        try: input()
        except: time.sleep(10)
    voter.close()
    sys.exit(0)

all_predictions.sort(key=lambda x: -x['ev'])
for i, p in enumerate(all_predictions):
    print(f"  {i+1}. {p['venue']}{p['race_number']}R 馬番{p['horse_number']} "
          f"odds={p['odds']:.1f} EV={p['ev']:.3f} ({p['surface']}{p['distance']}m) 発走{p.get('start_time','?')}")

best = all_predictions[0]
print(f"\n  → 最高EV: {best['venue']}{best['race_number']}R 馬番{best['horse_number']} "
      f"odds={best['odds']:.1f} EV={best['ev']:.3f}")

# ============================================================
# 6. 投票 or 確認のみ
# ============================================================
if args.execute:
    print(f"\n--- 投票実行 ---")
    for p in all_predictions:
        success, status = voter.place_bet(
            p['venue_code'], p['race_number'], p['horse_number'],
            amount=voter.bet_amount, ev=p['ev'],
            model_prob=p['model_prob'], odds_1min=p['odds']
        )
        print(f"  結果: {status}")
else:
    print(f"\n--- 投票画面に遷移（確認のみ）---")
    voter.navigate_to_bet_screen(best['venue'], best['race_number'], best['horse_number'])
    print(f"  投票画面を表示中: {best['venue']}{best['race_number']}R 馬番{best['horse_number']}")
    print(f"  単勝 {voter.bet_amount}円")
    print(f"\n  ★ 投票はしていません。ブラウザを確認してください。")
    print(f"  ★ 投票するには: python run_now.py --execute")

if not args.headless:
    print(f"\n  Enterキーで終了...")
    try: input()
    except: time.sleep(30)

voter.close()
print("Done!")
