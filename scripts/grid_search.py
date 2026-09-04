"""
総当たりパラメータ探索
Phase 1: スコアを事前計算 → ALPHA, BETA, SCALE, LOOKBACK の全組み合わせを高速テスト
"""
import sqlite3, math, time, sys
from collections import defaultdict, Counter

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

# === パラメータグリッド ===
ALPHAS = [0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
BETAS = [0.90, 0.95, 1.00, 1.03, 1.05, 1.10, 1.15, 1.20, 1.30]
SCALES = [0.03, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.30, 0.50]
LOOKBACKS = [1, 2]
BUDGET = 10000
TEST_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

total_combos = len(ALPHAS) * len(BETAS) * len(SCALES) * len(LOOKBACKS)
print(f"Grid: {len(ALPHAS)} ALPHA x {len(BETAS)} BETA x {len(SCALES)} SCALE x {len(LOOKBACKS)} LB = {total_combos} combos", flush=True)

# === Step 1: データ読み込み ===
t0 = time.time()
print("Loading races & entries...", flush=True)
races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}
print(f"  {len(races)} races, {len(entry_cache)} with entries ({time.time()-t0:.1f}s)", flush=True)

print("Loading trio odds...", flush=True)
trio_cache = defaultdict(dict)
rows = db.execute("SELECT race_id, combination, odds FROM odds WHERE bet_type='sanrenpuku'").fetchall()
for rid, combo, odds in rows:
    trio_cache[rid][combo] = odds
print(f"  {len(rows):,} trio odds loaded ({time.time()-t0:.1f}s)", flush=True)

# === Step 2: スコア事前計算 ===
print("Precomputing scores per (lookback, year)...", flush=True)
race_data = {}  # (lb, year) -> list of race dicts

for lb in LOOKBACKS:
    for test_year in TEST_YEARS:
        train_start = f'{test_year-lb}-01-01'
        train_end = f'{test_year}-01-01'
        test_start = f'{test_year}-01-01'
        test_end = f'{test_year+1}-01-01'

        jc = defaultdict(lambda:{'r':0,'w':0})
        hr = defaultdict(list)
        for rid,rd,vc,sf,dt in races:
            if rd < train_start or rd >= train_end: continue
            res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
            for hn,fp,hid in res:
                ent = entry_cache.get(rid,{}).get(hn,{})
                jn = ent.get('jockey','')
                if jn:
                    jc[jn]['r'] += 1
                    if fp == 1: jc[jn]['w'] += 1
                if hid:
                    hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
                    if len(hr[hid]) > 20: hr[hid] = hr[hid][-20:]

        # Capture jc/hr for this iteration
        _jc, _hr = jc, hr

        def make_scorer(jc_ref, hr_ref):
            def score(h, rid, vc, sf, dt):
                base = 50.0
                ent = entry_cache.get(rid,{}).get(h,{})
                hid = ent.get('hid',''); jn = ent.get('jockey','')
                jb = 0
                if jn and jn in jc_ref and jc_ref[jn]['r'] >= 20:
                    jb = (jc_ref[jn]['w']/jc_ref[jn]['r'] - 0.08) * 50
                hb = db_ = sb = vb = tb = 0
                if hid and hid in hr_ref:
                    rc = hr_ref[hid]
                    if len(rc) >= 2: hb = (6 - sum(r['fp'] for r in rc[-5:])/len(rc[-5:])) * 2
                    dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
                    if len(dr) >= 2: db_ = (6 - sum(r['fp'] for r in dr[-5:])/len(dr[-5:])) * 1.5
                    sr = [r for r in rc if r['surface'] == sf]
                    if len(sr) >= 2: sb = (6 - sum(r['fp'] for r in sr[-5:])/len(sr[-5:])) * 1.5
                    vr = [r for r in rc if r['venue'] == vc]
                    if len(vr) >= 2: vb = (6 - sum(r['fp'] for r in vr[-5:])/len(vr[-5:])) * 1.0
                    if len(rc) >= 3:
                        l3 = [r['fp'] for r in rc[-3:]]
                        if l3[-1] < l3[0]: tb = (l3[0] - l3[-1]) * 0.8
                return base + jb + hb + db_ + sb + vb + tb
            return score

        scorer = make_scorer(_jc, _hr)

        rd_list = []
        for rid,rd,vc,sf,dt in races:
            if rd < test_start or rd >= test_end: continue
            res = db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
            if len(res) < 5: continue
            t3 = [r[0] for r in res if r[1] <= 3]
            if len(t3) < 3: continue
            oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
            if not oz: continue
            om = {int(r[0]):r[1] for r in oz}
            hl = sorted(om.keys())
            if len(hl) < 5: continue
            early = [om[h] for h in hl]
            sc = [scorer(h, rid, vc, sf, dt) for h in hl]
            t3_set = frozenset(t3[:3])
            trio = trio_cache.get(rid, {})

            rd_list.append((hl, sc, early, om, t3_set, trio))

        race_data[(lb, test_year)] = rd_list
        print(f"  LB={lb} Year={test_year}: {len(rd_list)} races", flush=True)

print(f"Precomputation done ({time.time()-t0:.1f}s)", flush=True)

# === Step 3: 高速グリッドサーチ ===
print(f"\nStarting grid search ({total_combos} combos)...", flush=True)

def softmax(sc, scale):
    s = [(x-50)*scale for x in sc]
    mx = max(s)
    e = [math.exp(x-mx) for x in s]
    t = sum(e)
    return [x/t for x in e]

def mktp(odds, beta):
    inv = [1/o if o > 0 else 0 for o in odds]
    s = sum(inv)
    if s == 0: return [1/len(odds)]*len(odds)
    raw = [i/s for i in inv]
    pw = [p_**beta for p_ in raw]
    ps = sum(pw)
    return [p_/ps for p_ in pw]

def blendf(m, mk, alpha):
    bl = [math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s = sum(bl)
    return [p_/s for p_ in bl]

results = []
count = 0
t1 = time.time()

for lb in LOOKBACKS:
    for alpha in ALPHAS:
        for beta in BETAS:
            for scale in SCALES:
                yearly_rr = []
                total_bet = 0
                total_return = 0
                total_hits = 0
                total_races = 0

                for test_year in TEST_YEARS:
                    rd_list = race_data[(lb, test_year)]
                    tb = 0; tr = 0; hits = 0; rc = 0

                    for hl, sc, early, om, t3_set, trio in rd_list:
                        n = len(hl)
                        mp = softmax(sc, scale)
                        mkp = mktp(early, beta)

                        if alpha <= 0.001:
                            bp = mkp
                        elif alpha >= 0.999:
                            bp = mp
                        else:
                            bp = blendf(mp, mkp, alpha)

                        rk = sorted(range(n), key=lambda i: -bp[i])
                        top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
                        combo = f'{top[0]}-{top[1]}-{top[2]}'

                        odds_val = trio.get(combo, 0)
                        if odds_val <= 0: continue

                        tb += BUDGET; rc += 1
                        if frozenset(top) == t3_set:
                            tr += BUDGET * odds_val
                            hits += 1

                    rr = tr/tb*100 if tb > 0 else 0
                    yearly_rr.append(rr)
                    total_bet += tb
                    total_return += tr
                    total_hits += hits
                    total_races += rc

                total_rr = total_return/total_bet*100 if total_bet > 0 else 0
                plus_years = sum(1 for rr in yearly_rr if rr >= 100)

                results.append((
                    lb, alpha, beta, scale,
                    total_rr, plus_years,
                    yearly_rr, total_hits, total_races
                ))

                count += 1
                if count % 100 == 0:
                    elapsed = time.time() - t1
                    eta = elapsed / count * (total_combos - count)
                    print(f"  {count}/{total_combos} ({elapsed:.0f}s, ETA {eta:.0f}s)", flush=True)

print(f"Grid search done ({time.time()-t1:.1f}s)", flush=True)

# === Step 4: 結果出力 ===
# Sort by plus_years desc, then total_rr desc
results.sort(key=lambda r: (-r[5], -r[4]))

out = open(r'C:\Users\moribro2201\Desktop\grid_search_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

p('='*110)
p(f'=== 総当たりパラメータ探索結果 ({total_combos}通り) ===')
p('='*110)

p(f'\n--- Top 50 (プラス年数順 → 通算回収率順) ---')
p(f'{"#":>3} {"LB":>2} {"alpha":>6} {"beta":>5} {"scale":>5} {"通算":>6} {"P年":>3} {"的中":>5}  {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
p('-'*110)

for i, r in enumerate(results[:50]):
    lb, alpha, beta, scale, total_rr, plus_years, yearly_rr, hits, races_n = r
    yr_str = '  '.join(f'{rr:>5.1f}%' for rr in yearly_rr)
    p(f'{i+1:>3} {lb:>2} {alpha:>6.2f} {beta:>5.2f} {scale:>5.2f} {total_rr:>5.1f}% {plus_years:>3} {hits:>5}  {yr_str}')

# プラス年数の分布
p(f'\n--- プラス年数の分布 ---')
dist = Counter(r[5] for r in results)
for k in sorted(dist.keys(), reverse=True):
    p(f'  {k}年プラス: {dist[k]:>4}通り ({dist[k]/len(results)*100:.1f}%)')

# 通算回収率順 Top 20
results_by_rr = sorted(results, key=lambda r: -r[4])
p(f'\n--- Top 20 (通算回収率順) ---')
p(f'{"#":>3} {"LB":>2} {"alpha":>6} {"beta":>5} {"scale":>5} {"通算":>6} {"P年":>3} {"的中":>5}  {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
p('-'*110)
for i, r in enumerate(results_by_rr[:20]):
    lb, alpha, beta, scale, total_rr, plus_years, yearly_rr, hits, races_n = r
    yr_str = '  '.join(f'{rr:>5.1f}%' for rr in yearly_rr)
    p(f'{i+1:>3} {lb:>2} {alpha:>6.2f} {beta:>5.2f} {scale:>5.2f} {total_rr:>5.1f}% {plus_years:>3} {hits:>5}  {yr_str}')

# 2年以上プラスのものを全部表示
multi_plus = [r for r in results if r[5] >= 2]
multi_plus.sort(key=lambda r: (-r[5], -r[4]))
p(f'\n--- 2年以上プラスの全パラメータ ({len(multi_plus)}通り) ---')
p(f'{"#":>3} {"LB":>2} {"alpha":>6} {"beta":>5} {"scale":>5} {"通算":>6} {"P年":>3} {"的中":>5}  {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
p('-'*110)
for i, r in enumerate(multi_plus[:100]):
    lb, alpha, beta, scale, total_rr, plus_years, yearly_rr, hits, races_n = r
    yr_str = '  '.join(f'{rr:>5.1f}%' for rr in yearly_rr)
    p(f'{i+1:>3} {lb:>2} {alpha:>6.2f} {beta:>5.2f} {scale:>5.02f} {total_rr:>5.1f}% {plus_years:>3} {hits:>5}  {yr_str}')

# 全体統計
p(f'\n--- 全体統計 ---')
p(f'  テスト数: {len(results)}')
p(f'  通算プラス(>=100%): {sum(1 for r in results if r[4]>=100)}通り')
p(f'  最高通算回収率: {results_by_rr[0][4]:.1f}%')
p(f'  最多プラス年数: {results[0][5]}年')
avg_rr = sum(r[4] for r in results) / len(results)
p(f'  平均通算回収率: {avg_rr:.1f}%')

# ALPHA別の平均回収率
p(f'\n--- ALPHA別の平均回収率 ---')
for alpha in ALPHAS:
    subset = [r for r in results if r[1] == alpha]
    avg = sum(r[4] for r in subset) / len(subset)
    best = max(r[4] for r in subset)
    plus_any = sum(1 for r in subset if r[5] >= 1)
    p(f'  alpha={alpha:.2f}: 平均{avg:.1f}% 最高{best:.1f}% 1年以上プラス{plus_any}/{len(subset)}')

# BETA別
p(f'\n--- BETA別の平均回収率 ---')
for beta in BETAS:
    subset = [r for r in results if r[2] == beta]
    avg = sum(r[4] for r in subset) / len(subset)
    best = max(r[4] for r in subset)
    p(f'  beta={beta:.2f}: 平均{avg:.1f}% 最高{best:.1f}%')

# SCALE別
p(f'\n--- SCALE別の平均回収率 ---')
for scale in SCALES:
    subset = [r for r in results if r[3] == scale]
    avg = sum(r[4] for r in subset) / len(subset)
    best = max(r[4] for r in subset)
    p(f'  scale={scale:.2f}: 平均{avg:.1f}% 最高{best:.1f}%')

db.close()
out.close()
print(f"\nDone! Results: C:\\Users\\moribro2201\\Desktop\\grid_search_results.txt")
print(f"Total time: {time.time()-t0:.1f}s", flush=True)
