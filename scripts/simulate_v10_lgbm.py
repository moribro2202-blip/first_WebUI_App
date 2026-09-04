"""
v10: LightGBMによる三連複予測
- 2024-2025で学習 → 2026でテスト
- 各馬の「3着以内に入る確率」を予測
- 上位3頭で三連複1点買い
"""
import sqlite3, math, sys, numpy as np
from collections import defaultdict
import lightgbm as lgb

out = open(r'C:\Users\moribro2201\Desktop\simulation_v10.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

p('=== v10: LightGBM 三連複予測 ===\n')

# --- データ準備 ---
p('Phase 1: 特徴量構築...')

# 累積統計
jc = defaultdict(lambda:{'r':0,'w':0,'p3':0})  # 騎手
hr = defaultdict(list)  # 馬の成績履歴
horse_last_race = {}

# 全レース取得
races = db.execute('''
    SELECT r.race_id, r.race_date, r.venue_code, r.surface, r.distance, r.race_number
    FROM races r ORDER BY r.race_date, r.race_id
''').fetchall()

entry_cache = {}
for rid,_,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,carried_weight FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'weight':e[3]} for e in es}

def build_features(h, rid, vc, sf, dt, rnum, n_horses, odds, market_rank):
    """各馬の特徴量ベクトルを構築"""
    ent = entry_cache.get(rid, {}).get(h, {})
    hid = ent.get('hid', ''); jn = ent.get('jockey', '')
    wt = ent.get('weight', 0) or 0

    feats = {}

    # 市場情報
    feats['odds'] = odds
    feats['market_rank'] = market_rank
    feats['log_odds'] = math.log(odds) if odds > 0 else 5
    feats['market_prob'] = 1/odds if odds > 0 else 0
    feats['n_horses'] = n_horses
    feats['horse_number'] = h
    feats['race_number'] = rnum
    feats['carried_weight'] = wt

    # 騎手
    if jn and jn in jc and jc[jn]['r'] >= 10:
        feats['jockey_win_rate'] = jc[jn]['w'] / jc[jn]['r']
        feats['jockey_place_rate'] = jc[jn]['p3'] / jc[jn]['r']
        feats['jockey_rides'] = min(jc[jn]['r'], 1000)
    else:
        feats['jockey_win_rate'] = 0.08
        feats['jockey_place_rate'] = 0.25
        feats['jockey_rides'] = 0

    # 馬の成績
    if hid and hid in hr:
        rc = hr[hid]
        recent = rc[-5:]
        feats['horse_avg_pos'] = sum(r['fp'] for r in recent) / len(recent)
        feats['horse_best_pos'] = min(r['fp'] for r in recent)
        feats['horse_runs'] = min(len(rc), 20)
        feats['horse_win_rate'] = sum(1 for r in rc if r['fp'] == 1) / len(rc)
        feats['horse_place_rate'] = sum(1 for r in rc if r['fp'] <= 3) / len(rc)

        # 距離適性
        dr = [r for r in rc if r['dist'] and abs(r['dist'] - dt) <= 200]
        if len(dr) >= 2:
            feats['dist_avg'] = sum(r['fp'] for r in dr[-5:]) / len(dr[-5:])
            feats['dist_place_rate'] = sum(1 for r in dr if r['fp'] <= 3) / len(dr)
        else:
            feats['dist_avg'] = feats['horse_avg_pos']
            feats['dist_place_rate'] = feats['horse_place_rate']

        # 馬場適性
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2:
            feats['surf_avg'] = sum(r['fp'] for r in sr[-5:]) / len(sr[-5:])
        else:
            feats['surf_avg'] = feats['horse_avg_pos']

        # 競馬場適性
        vr = [r for r in rc if r['venue'] == vc]
        if len(vr) >= 2:
            feats['venue_avg'] = sum(r['fp'] for r in vr[-5:]) / len(vr[-5:])
        else:
            feats['venue_avg'] = feats['horse_avg_pos']

        # トレンド
        if len(recent) >= 3:
            feats['trend'] = recent[0]['fp'] - recent[-1]['fp']  # 正=改善
        else:
            feats['trend'] = 0

        # 前走間隔
        if hid in horse_last_race:
            from datetime import datetime
            try:
                rd_row = db.execute("SELECT race_date FROM races WHERE race_id=?", (rid,)).fetchone()
                if rd_row:
                    cur = datetime.strptime(rd_row[0], '%Y-%m-%d')
                    last = datetime.strptime(horse_last_race[hid], '%Y-%m-%d')
                    feats['days_since'] = min((cur - last).days, 365)
                else:
                    feats['days_since'] = 30
            except:
                feats['days_since'] = 30
        else:
            feats['days_since'] = 180
    else:
        feats['horse_avg_pos'] = 8
        feats['horse_best_pos'] = 5
        feats['horse_runs'] = 0
        feats['horse_win_rate'] = 0
        feats['horse_place_rate'] = 0
        feats['dist_avg'] = 8
        feats['dist_place_rate'] = 0
        feats['surf_avg'] = 8
        feats['venue_avg'] = 8
        feats['trend'] = 0
        feats['days_since'] = 180

    return feats

FEATURE_NAMES = [
    'odds','market_rank','log_odds','market_prob','n_horses','horse_number',
    'race_number','carried_weight','jockey_win_rate','jockey_place_rate',
    'jockey_rides','horse_avg_pos','horse_best_pos','horse_runs',
    'horse_win_rate','horse_place_rate','dist_avg','dist_place_rate',
    'surf_avg','venue_avg','trend','days_since'
]

# --- 学習データ構築（2024-2025） ---
X_train = []; y_train = []
train_count = 0

for rid, rd, vc, sf, dt, rnum in races:
    if rd >= '2026-01-01': break

    res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
    if len(res) < 5: continue

    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if not oz: continue
    om = {int(r[0]):r[1] for r in oz}
    hl = sorted(om.keys())
    if len(hl) < 5: continue

    # オッズ順位
    odds_sorted = sorted(hl, key=lambda h: om.get(h, 999))
    odds_rank = {h: i+1 for i, h in enumerate(odds_sorted)}

    for hn, fp, hid in res:
        if hn not in om: continue
        feats = build_features(hn, rid, vc, sf, dt, rnum, len(hl), om[hn], odds_rank.get(hn, len(hl)))
        X_train.append([feats[f] for f in FEATURE_NAMES])
        y_train.append(1 if fp <= 3 else 0)

    # 成績を累積に追加（学習後）
    for hn, fp, hid in res:
        ent = entry_cache.get(rid, {}).get(hn, {})
        jn = ent.get('jockey', '')
        if jn:
            jc[jn]['r'] += 1
            if fp == 1: jc[jn]['w'] += 1
            if fp <= 3: jc[jn]['p3'] += 1
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid]) > 20: hr[hid] = hr[hid][-20:]
            horse_last_race[hid] = rd

    train_count += 1

X_train = np.array(X_train, dtype=np.float32)
y_train = np.array(y_train, dtype=np.int32)

p(f'Training data: {len(X_train)} samples ({train_count} races), positive rate: {y_train.mean():.3f}')

# --- LightGBM学習 ---
p('Phase 2: LightGBM学習...')

train_data = lgb.Dataset(X_train, label=y_train, feature_name=FEATURE_NAMES)

params = {
    'objective': 'binary',
    'metric': 'binary_logloss',
    'learning_rate': 0.05,
    'num_leaves': 31,
    'max_depth': 6,
    'min_child_samples': 50,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'reg_alpha': 0.1,
    'reg_lambda': 1.0,
    'verbose': -1,
    'seed': 42,
}

model = lgb.train(params, train_data, num_boost_round=300)

# 特徴量重要度
p('\n特徴量重要度:')
importance = model.feature_importance(importance_type='gain')
for fname, imp in sorted(zip(FEATURE_NAMES, importance), key=lambda x: -x[1]):
    p(f'  {fname:<25} {imp:>10.1f}')

# --- 2026年テスト ---
p('\nPhase 3: 2026年シミュレーション...')

BUDGET = 10000
tb=0;tr=0;traces=0;thits=0
mo = defaultdict(lambda:{'b':0,'r':0,'n':0})

# v7ベースラインも同時計算
tb7=0;tr7=0;thits7=0

for rid, rd, vc, sf, dt, rnum in races:
    if rd < '2026-01-01': continue

    res = db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
    if len(res) < 5: continue
    t3 = [r[0] for r in res if r[1] <= 3]
    if len(t3) < 3: continue

    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if not oz: continue
    om = {int(r[0]):r[1] for r in oz}
    hl = sorted(om.keys())
    if len(hl) < 5: continue

    odds_sorted = sorted(hl, key=lambda h: om.get(h, 999))
    odds_rank = {h: i+1 for i, h in enumerate(odds_sorted)}

    # LightGBM予測
    X_test = []
    for h in hl:
        feats = build_features(h, rid, vc, sf, dt, rnum, len(hl), om[h], odds_rank.get(h, len(hl)))
        X_test.append([feats[f] for f in FEATURE_NAMES])

    X_test = np.array(X_test, dtype=np.float32)
    preds = model.predict(X_test)

    # 上位3頭
    top3_idx = np.argsort(-preds)[:3]
    top_hn = [hl[i] for i in top3_idx]

    combo = '-'.join(str(h) for h in sorted(top_hn))
    orow = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
    if not orow or orow[0] <= 0: continue

    odds = orow[0]; hit = set(top_hn) == set(t3[:3])
    tb += BUDGET; traces += 1
    month = rd[:7]; mo[month]['b'] += BUDGET; mo[month]['n'] += 1
    if hit: tr += BUDGET * odds; thits += 1; mo[month]['r'] += BUDGET * odds

    # 成績更新（ウォークフォワード）
    res2 = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
    for hn, fp, hid in res2:
        ent = entry_cache.get(rid, {}).get(hn, {})
        jn = ent.get('jockey', '')
        if jn:
            jc[jn]['r'] += 1
            if fp == 1: jc[jn]['w'] += 1
            if fp <= 3: jc[jn]['p3'] += 1
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid]) > 20: hr[hid] = hr[hid][-20:]
            horse_last_race[hid] = rd

rr = tr/tb*100 if tb>0 else 0

p(f'\n{"="*80}')
p(f'=== v10 LightGBM結果 ===')
p(f'{"="*80}')
p(f'レース数: {traces}')
p(f'的中: {thits} ({thits/traces*100:.1f}%)')
p(f'投資: {tb:,.0f}円')
p(f'払戻: {tr:,.0f}円')
p(f'収支: {tr-tb:+,.0f}円')
p(f'回収率: {rr:.1f}%')

p(f'\n月別:')
cb=0;cr=0
for m in sorted(mo.keys()):
    d=mo[m]; cb+=d['b'];cr+=d['r']
    p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

p(f'\n=== v7 vs v10 比較 ===')
p(f'v7(手動スコア): 回収率110.4% 収支+2,044,000円')
p(f'v10(LightGBM): 回収率{rr:.1f}% 収支{tr-tb:+,.0f}円')
p(f'差分: {rr-110.4:+.1f}pt')

db.close(); out.close()
