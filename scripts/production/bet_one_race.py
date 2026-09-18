# -*- coding: utf-8 -*-
"""1レース投票テスト: オッズ取得 → EV計算 → 100円投票"""
import sys, time, re, json, math, sqlite3
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))

BASE = __import__('os').path.join(__import__('os').path.dirname(__import__('os').path.abspath(__file__)), '..', '..')
DB_PATH = f'{BASE}/data/jrdb.db'
MODEL_DIR = f'{BASE}/data/models'

from ipat_voter import IPATVoter

# 1. ログイン
print("=" * 50)
print("=== 1レース投票テスト ===")
print("=" * 50)
voter = IPATVoter(headless=False)
voter.login()
time.sleep(2)

# 2. オッズ投票ページ → 1R選択
base_url = voter.page.url.split('#!/')[0]
voter.page.goto(f'{base_url}#!/bet/odds/type', timeout=10000)
time.sleep(3)

# 1Rをクリック
spans = voter.page.locator('span').all()
for span in spans:
    text = (span.text_content() or '').strip()
    if text == '1R':
        span.click()
        print('1R選択')
        break
time.sleep(2)
voter._screenshot('race_1R')

# 3. オッズ取得
html = voter.page.evaluate('document.body.innerHTML')
odds = {}
rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE)
for row in rows:
    cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
    if len(cells) >= 3:
        try:
            hn_text = re.sub(r'<[^>]+>', '', cells[0]).strip()
            hn = int(hn_text)
            if hn < 1 or hn > 18:
                continue
            for cell in cells[2:]:
                cell_text = re.sub(r'<[^>]+>', '', cell).strip()
                m = re.match(r'^(\d+\.?\d*)$', cell_text)
                if m:
                    odds_val = float(m.group(1))
                    if 1.0 <= odds_val <= 9999:
                        odds[hn] = odds_val
                        break
        except:
            pass

print(f'\nオッズ: {len(odds)}頭')
if not odds:
    # AngularのngBindingから探す
    print('通常パース失敗。ng-binding要素を探索...')
    bindings = voter.page.locator('.ng-binding').all()
    print(f'  ng-binding要素: {len(bindings)}個')
    texts = []
    for b in bindings[:50]:
        t = (b.text_content() or '').strip()
        if t:
            texts.append(t)
    print(f'  テキスト: {texts[:30]}')

    # テーブル行から取得を試みる
    trs = voter.page.locator('tr').all()
    print(f'  tr要素: {len(trs)}個')
    for tr in trs:
        tds = tr.locator('td').all()
        if len(tds) >= 3:
            texts_row = []
            for td in tds:
                t = (td.text_content() or '').strip()
                texts_row.append(t)
            # 馬番(数字) + 馬名 + オッズ(数字)のパターン
            try:
                hn = int(texts_row[0])
                if 1 <= hn <= 18:
                    for t in texts_row[2:]:
                        m = re.match(r'^(\d+\.?\d*)$', t)
                        if m:
                            odds[hn] = float(m.group(1))
                            break
            except:
                pass

    print(f'  再取得: {len(odds)}頭')

if odds:
    for hn in sorted(odds.keys()):
        print(f'  馬番{hn:>2}: {odds[hn]:>6.1f}倍')
else:
    print('オッズ取得失敗。ブラウザを確認してください。')
    time.sleep(30)
    voter.close()
    sys.exit(1)

# 4. モデル予測
import lightgbm as lgb
with open(f'{MODEL_DIR}/prod_config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)
model = lgb.Booster(model_file=f'{MODEL_DIR}/{config["model_file"]}')
feature_names = config['feature_names']
b_param = config['b']
tau_param = config['tau']
beta = config['beta']
ev_threshold = config['ev_threshold']
with open(f'{MODEL_DIR}/{config["stats_file"]}', 'r', encoding='utf-8') as f:
    stats = json.load(f)

# DBからエントリー
db = sqlite3.connect(DB_PATH)
from datetime import datetime, timedelta

race_row = None
for d in range(0, 3):
    dt_cand = (datetime.now() + timedelta(days=d)).strftime('%Y-%m-%d')
    rows = db.execute(
        'SELECT race_id,race_date,surface,distance,track_condition,grade '
        'FROM races WHERE venue_code=? AND race_number=? AND race_date=?',
        ('06', 1, dt_cand)
    ).fetchall()
    if rows:
        race_row = rows[0]
        break

if not race_row:
    print(f'\nDBにレースデータなし（JRDBインポートが必要）')
    print(f'オッズのみでEV計算なし。ブラウザを確認してください。')
    time.sleep(30)
    voter.close()
    sys.exit(0)

rid, rd, sf, dist, tc, grade = race_row
print(f'\nレース: {rid} {rd} {sf}{dist}m {tc or "良"}')

entries = {}
for row in db.execute(
    'SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight '
    'FROM entries WHERE race_id=?', (rid,)
).fetchall():
    entries[row[0]] = {
        'hid': row[1], 'jockey': row[2], 'trainer': row[3], 'idm': row[4],
        'total': row[5], 'rider': row[6], 'run_style': row[7], 'weight': row[8]
    }
db.close()

horses = sorted(entries.keys())
n = len(horses)
print(f'エントリー: {n}頭')

# 市場確率
inv = np.array([1 / odds.get(h, 999) for h in horses])
mp = inv / inv.sum()
mp = mp ** beta
mp = mp / mp.sum()

grade_map = {'G1': 6, 'G2': 5, 'G3': 4, 'OP': 3, 'L': 2, '3勝': 1, '2勝': 0,
             '1勝': -1, '未勝利': -2, '新馬': -3, '一般': 0}
tc_map = {'良': 0, '稍重': 1, '重': 2, '不良': 3}
sf_map = {'芝': 0, 'ダート': 1}

idms = [entries.get(h, {}).get('idm') or 50 for h in horses]
avg_idm = np.mean(idms)
riders = [entries.get(h, {}).get('rider') or 0 for h in horses]
avg_rider = np.mean(riders)

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
    f['expert_resid'] = 0
    f['cyb_c'] = 0
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
    f['track_cond'] = tc_map.get(tc or '良', 0)
    f['grade'] = grade_map.get(grade or '一般', 0)
    f['is_senkou'] = 1 if ent.get('run_style', '') in ('逃げ', '先行') else 0
    f['gate_ratio'] = h / n
    cw = ent.get('weight') or 0
    avg_cw = np.mean([entries.get(h2, {}).get('weight') or 0 for h2 in horses])
    f['weight_c'] = (cw - avg_cw) if cw > 0 else 0
    f['move_5to1'] = 0
    X.append([f.get(k, 0) for k in feature_names])
    p = mp[i]
    init_scores.append(math.log(max(p, 1e-15)) - math.log(max(1 - p, 1e-15)))

X = np.array(X, dtype=np.float32)
init_scores = np.array(init_scores, dtype=np.float64)

raw = model.predict(X, raw_score=True)
s = b_param * init_scores + tau_param * raw
s -= s.max()
probs = np.exp(s) / np.exp(s).sum()

# EV表示
print(f'\n  馬番  オッズ  モデルP    EV')
print(f'  {"─" * 35}')
best_hn = None
best_ev = 0
for i, h in enumerate(horses):
    o = odds.get(h, 0)
    ev = probs[i] * o if o > 0 else 0
    mark = ' ★' if ev >= ev_threshold else ''
    print(f'  {h:>4} {o:>6.1f}x {probs[i]:>6.3f} {ev:>5.2f}{mark}')
    if ev > best_ev:
        best_ev = ev
        best_hn = h

print(f'\n  → 最高EV: 馬番{best_hn} EV={best_ev:.3f} odds={odds.get(best_hn, 0):.1f}')

# 5. 投票（100円）
print(f'\n=== 馬番{best_hn}に単勝100円投票 ===')

# オッズテーブルで馬番をクリック
trs = voter.page.locator('tr').all()
clicked = False
for tr in trs:
    tds = tr.locator('td').all()
    if len(tds) >= 3:
        first_text = (tds[0].text_content() or '').strip()
        try:
            if int(first_text) == best_hn:
                # 単勝オッズのセルをクリック
                tds[2].click()
                clicked = True
                print(f'  馬番{best_hn}をクリック')
                break
        except:
            pass

if not clicked:
    print(f'  馬番{best_hn}のクリック失敗。ブラウザで手動確認してください。')
    time.sleep(30)
    voter.close()
    sys.exit(1)

time.sleep(2)
voter._screenshot('after_horse_select')

# 金額入力
inputs = voter.page.locator('input[type="text"], input[type="number"]').all()
for inp in inputs:
    try:
        val = inp.input_value()
        if not val or val == '0':
            inp.fill('1')
            print(f'  金額: 1口(100円)')
            break
    except:
        pass

time.sleep(1)
voter._screenshot('after_amount')

# セット
try:
    voter.page.click('text=セット', timeout=3000)
    print(f'  セット完了')
    time.sleep(2)
except:
    print(f'  セットボタン見つからず')

voter._screenshot('after_set')

# 投票
try:
    voter.page.click('text=投票', timeout=3000)
    print(f'  投票クリック')
    time.sleep(2)
except:
    print(f'  投票ボタン見つからず')

voter._screenshot('after_bet')

content = voter.page.evaluate('document.body.innerText')
if '受付' in content or '完了' in content:
    print(f'\n  ★ 投票成功！ 馬番{best_hn} 単勝 100円')
else:
    print(f'\n  ブラウザを確認してください。')

print(f'\n30秒後に終了...')
time.sleep(30)
voter.close()
print('Done!')
