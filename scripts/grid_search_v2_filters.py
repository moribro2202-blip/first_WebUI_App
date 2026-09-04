"""
総当たりパラメータ探索 Phase 2: 選択的ベッティング（確信度フィルタ）
ベースパラメータ(α,β,scale,LB)のtop3確率を事前計算 → フィルタ条件で高速絞り込み

フィルタ:
  F1: min_top3_prob  - ブレンド確率上位3頭の合計が閾値以上（確信度）
  F2: divergence     - モデルtop3と市場top3の乖離度（-1=全部, 0=一致のみ, 1+=乖離あり）
  F3: max_trio_odds  - 三連複オッズの上限（高配当を避ける）
  F4: max_horses     - 出走頭数の上限（少頭数のみ）
  F5: min_top1_prob  - 1位候補の最低確率（圧倒的本命がいるレース）
"""
import sqlite3, math, time
from collections import defaultdict, Counter

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

# === ベースパラメータグリッド ===
ALPHAS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
BETAS = [1.00, 1.03, 1.10]
SCALES = [0.05, 0.10, 0.15, 0.20, 0.30]
LOOKBACKS = [1, 2]
BUDGET = 10000
TEST_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

# === フィルタグリッド ===
MIN_TOP3_PROBS = [0.0, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
DIVERGENCE_MODES = [-1, 0, 1]  # -1=全部, 0=市場一致のみ, 1=乖離ありのみ
MAX_TRIO_ODDS = [9999, 100, 50, 30, 20, 15, 10]
MAX_HORSES_LIST = [99, 16, 14, 12, 10, 8]
MIN_TOP1_PROBS = [0.0, 0.15, 0.20, 0.25, 0.30]

base_combos = len(ALPHAS) * len(BETAS) * len(SCALES) * len(LOOKBACKS)
filter_combos = len(MIN_TOP3_PROBS) * len(DIVERGENCE_MODES) * len(MAX_TRIO_ODDS) * len(MAX_HORSES_LIST) * len(MIN_TOP1_PROBS)
print(f"Base: {base_combos} combos x Filters: {filter_combos} = {base_combos * filter_combos:,} total", flush=True)

# === Step 1: データ読み込み ===
t0 = time.time()
print("Loading data...", flush=True)
races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

print("Loading trio odds...", flush=True)
trio_cache = defaultdict(dict)
for rid, combo, odds in db.execute("SELECT race_id, combination, odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    trio_cache[rid][combo] = odds
print(f"  Loaded ({time.time()-t0:.1f}s)", flush=True)

# === Step 2: スコア事前計算 ===
print("Precomputing scores...", flush=True)
race_data = {}

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
            # Market top 3 (by lowest win odds) - independent of parameters
            mkt_top3 = set(sorted(hl, key=lambda h: om[h])[:3])

            rd_list.append((hl, sc, early, om, t3_set, trio, mkt_top3, len(hl)))

        race_data[(lb, test_year)] = rd_list
        print(f"  LB={lb} Year={test_year}: {len(rd_list)} races", flush=True)

print(f"Precomputation done ({time.time()-t0:.1f}s)", flush=True)
db.close()

# === Step 3: グリッドサーチ ===
print(f"\nStarting grid search...", flush=True)

def softmax(sc, scale):
    s = [(x-50)*scale for x in sc]; mx = max(s)
    e = [math.exp(x-mx) for x in s]; t = sum(e)
    return [x/t for x in e]

def mktp(odds, beta):
    inv = [1/o if o > 0 else 0 for o in odds]; s = sum(inv)
    if s == 0: return [1/len(odds)]*len(odds)
    raw = [i/s for i in inv]; pw = [p_**beta for p_ in raw]; ps = sum(pw)
    return [p_/ps for p_ in pw]

def blendf(m, mk, alpha):
    bl = [math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s = sum(bl); return [p_/s for p_ in bl]

# Store all results, but only keep promising ones to save memory
top_results = []  # will keep top 500
MIN_RACES_PER_YEAR = 30  # 年あたり最低レース数

t1 = time.time()
base_count = 0

for lb in LOOKBACKS:
    for alpha in ALPHAS:
        for beta in BETAS:
            for scale in SCALES:
                base_count += 1

                # Phase A: Compute blended probs and metrics for all races
                # race_metrics[year] = list of (hit, payout, top3_prob_sum, top1_prob, divergence_count, trio_odds, num_horses)
                race_metrics = {y: [] for y in TEST_YEARS}

                for test_year in TEST_YEARS:
                    rd_list = race_data[(lb, test_year)]

                    for hl, sc, early, om, t3_set, trio, mkt_top3, num_h in rd_list:
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

                        top3_prob = bp[rk[0]] + bp[rk[1]] + bp[rk[2]]
                        top1_prob = bp[rk[0]]
                        model_top3_set = set(top)
                        div_count = len(model_top3_set - mkt_top3)
                        hit = frozenset(top) == t3_set
                        payout = BUDGET * odds_val if hit else 0

                        race_metrics[test_year].append((
                            hit, payout, top3_prob, top1_prob,
                            div_count, odds_val, num_h
                        ))

                # Phase B: Apply all filter combinations
                for min_t3p in MIN_TOP3_PROBS:
                    for div_mode in DIVERGENCE_MODES:
                        for max_odds in MAX_TRIO_ODDS:
                            for max_h in MAX_HORSES_LIST:
                                for min_t1p in MIN_TOP1_PROBS:
                                    yearly_rr = []
                                    total_bet = 0
                                    total_ret = 0
                                    total_hits = 0
                                    total_races = 0
                                    skip_year = False

                                    for test_year in TEST_YEARS:
                                        tb = 0; tr = 0; hits = 0; rc = 0
                                        for hit, payout, t3p, t1p, div_n, todds, nh in race_metrics[test_year]:
                                            if t3p < min_t3p: continue
                                            if min_t1p > 0 and t1p < min_t1p: continue
                                            if div_mode == 0 and div_n > 0: continue
                                            if div_mode == 1 and div_n == 0: continue
                                            if todds > max_odds: continue
                                            if nh > max_h: continue
                                            tb += BUDGET; rc += 1
                                            if hit:
                                                tr += payout; hits += 1

                                        if rc < MIN_RACES_PER_YEAR:
                                            skip_year = True; break

                                        rr = tr/tb*100 if tb > 0 else 0
                                        yearly_rr.append(rr)
                                        total_bet += tb
                                        total_ret += tr
                                        total_hits += hits
                                        total_races += rc

                                    if skip_year: continue

                                    total_rr = total_ret/total_bet*100 if total_bet > 0 else 0
                                    plus_years = sum(1 for rr in yearly_rr if rr >= 100)

                                    # Keep if promising (2+ plus years or total_rr >= 95%)
                                    if plus_years >= 2 or total_rr >= 95:
                                        top_results.append((
                                            lb, alpha, beta, scale,
                                            min_t3p, div_mode, max_odds, max_h, min_t1p,
                                            total_rr, plus_years, yearly_rr,
                                            total_hits, total_races
                                        ))

                if base_count % 10 == 0:
                    elapsed = time.time() - t1
                    eta = elapsed / base_count * (base_combos - base_count)
                    print(f"  Base {base_count}/{base_combos} ({elapsed:.0f}s, ETA {eta:.0f}s) kept={len(top_results)}", flush=True)

print(f"Grid search done ({time.time()-t1:.1f}s), {len(top_results)} promising results", flush=True)

# === Step 4: 結果出力 ===
top_results.sort(key=lambda r: (-r[10], -r[9]))  # plus_years desc, total_rr desc

out = open(r'C:\Users\moribro2201\Desktop\grid_search_v2_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

div_labels = {-1: '全部', 0: '一致', 1: '乖離'}

p('='*130)
p(f'=== 総当たり探索 Phase2: 選択的ベッティング ===')
p(f'=== ベース{base_combos} x フィルタ{filter_combos} = {base_combos*filter_combos:,}通り ===')
p(f'=== 年あたり最低{MIN_RACES_PER_YEAR}R以上 & (2年以上プラス or 通算95%以上) を記録 ===')
p('='*130)

# --- Top 100 by plus years ---
p(f'\n--- Top 100 (プラス年数順 → 通算回収率順) ---')
header = f'{"#":>3} {"LB":>2} {"α":>4} {"β":>4} {"SC":>4} | {"T3P":>4} {"Div":>4} {"MxO":>5} {"MxH":>3} {"T1P":>4} | {"通算":>6} {"P年":>2} {"R数":>5} {"的中":>4} | {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}'
p(header)
p('-'*130)

for i, r in enumerate(top_results[:100]):
    lb, alpha, beta, scale, min_t3p, div_mode, max_odds, max_h, min_t1p, total_rr, plus_years, yearly_rr, hits, races_n = r
    yr_str = ' '.join(f'{rr:>6.1f}%' for rr in yearly_rr)
    mo = f'{max_odds}' if max_odds < 9999 else '∞'
    mh = f'{max_h}' if max_h < 99 else '∞'
    p(f'{i+1:>3} {lb:>2} {alpha:>.2f} {beta:>.2f} {scale:>.2f} | {min_t3p:>.2f} {div_labels[div_mode]:>4} {mo:>5} {mh:>3} {min_t1p:>.2f} | {total_rr:>5.1f}% {plus_years:>2} {races_n:>5} {hits:>4} | {yr_str}')

# --- 通算プラスのもの ---
profitable = [r for r in top_results if r[9] >= 100]
profitable.sort(key=lambda r: -r[9])
p(f'\n--- 通算プラス(回収率>=100%) ({len(profitable)}通り) ---')
p(header)
p('-'*130)
for i, r in enumerate(profitable[:100]):
    lb, alpha, beta, scale, min_t3p, div_mode, max_odds, max_h, min_t1p, total_rr, plus_years, yearly_rr, hits, races_n = r
    yr_str = ' '.join(f'{rr:>6.1f}%' for rr in yearly_rr)
    mo = f'{max_odds}' if max_odds < 9999 else '∞'
    mh = f'{max_h}' if max_h < 99 else '∞'
    p(f'{i+1:>3} {lb:>2} {alpha:>.2f} {beta:>.2f} {scale:>.2f} | {min_t3p:>.2f} {div_labels[div_mode]:>4} {mo:>5} {mh:>3} {min_t1p:>.2f} | {total_rr:>5.1f}% {plus_years:>2} {races_n:>5} {hits:>4} | {yr_str}')

# --- プラス年数の分布 ---
p(f'\n--- プラス年数の分布（記録された結果のみ） ---')
dist = Counter(r[10] for r in top_results)
for k in sorted(dist.keys(), reverse=True):
    p(f'  {k}年プラス: {dist[k]:>5}通り')

# --- フィルタ別の効果分析 ---
p(f'\n--- フィルタ別の効果（通算プラスの割合） ---')

p(f'\n  min_top3_prob別:')
for v in MIN_TOP3_PROBS:
    subset = [r for r in top_results if r[4] == v]
    if not subset: continue
    prof = sum(1 for r in subset if r[9] >= 100)
    avg_rr = sum(r[9] for r in subset)/len(subset) if subset else 0
    avg_races = sum(r[13] for r in subset)/len(subset) if subset else 0
    p(f'    >={v:.2f}: {len(subset):>5}件 プラス{prof:>4} 平均RR{avg_rr:.1f}% 平均R数{avg_races:.0f}')

p(f'\n  divergence_mode別:')
for v in DIVERGENCE_MODES:
    subset = [r for r in top_results if r[5] == v]
    if not subset: continue
    prof = sum(1 for r in subset if r[9] >= 100)
    avg_rr = sum(r[9] for r in subset)/len(subset) if subset else 0
    p(f'    {div_labels[v]}: {len(subset):>5}件 プラス{prof:>4} 平均RR{avg_rr:.1f}%')

p(f'\n  max_trio_odds別:')
for v in MAX_TRIO_ODDS:
    subset = [r for r in top_results if r[6] == v]
    if not subset: continue
    prof = sum(1 for r in subset if r[9] >= 100)
    avg_rr = sum(r[9] for r in subset)/len(subset) if subset else 0
    vl = f'{v}' if v < 9999 else '∞'
    p(f'    <={vl:>5}: {len(subset):>5}件 プラス{prof:>4} 平均RR{avg_rr:.1f}%')

p(f'\n  max_horses別:')
for v in MAX_HORSES_LIST:
    subset = [r for r in top_results if r[7] == v]
    if not subset: continue
    prof = sum(1 for r in subset if r[9] >= 100)
    avg_rr = sum(r[9] for r in subset)/len(subset) if subset else 0
    vl = f'{v}' if v < 99 else '∞'
    p(f'    <={vl:>3}: {len(subset):>5}件 プラス{prof:>4} 平均RR{avg_rr:.1f}%')

p(f'\n  min_top1_prob別:')
for v in MIN_TOP1_PROBS:
    subset = [r for r in top_results if r[8] == v]
    if not subset: continue
    prof = sum(1 for r in subset if r[9] >= 100)
    avg_rr = sum(r[9] for r in subset)/len(subset) if subset else 0
    p(f'    >={v:.2f}: {len(subset):>5}件 プラス{prof:>4} 平均RR{avg_rr:.1f}%')

# --- 全体統計 ---
p(f'\n--- 全体統計 ---')
p(f'  記録数: {len(top_results)}')
p(f'  通算プラス: {len(profitable)}通り')
if top_results:
    p(f'  最高通算回収率: {max(r[9] for r in top_results):.1f}%')
    p(f'  最多プラス年数: {max(r[10] for r in top_results)}年')
if profitable:
    best = profitable[0]
    p(f'\n  ベスト設定:')
    p(f'    LB={best[0]} α={best[1]} β={best[2]} scale={best[3]}')
    p(f'    min_top3_prob={best[4]} div={div_labels[best[5]]} max_odds={best[6]} max_horses={best[7]} min_top1={best[8]}')
    p(f'    通算{best[9]:.1f}% {best[10]}年プラス {best[13]}R {best[11]}的中')

out.close()
print(f"\nDone! Results: C:\\Users\\moribro2201\\Desktop\\grid_search_v2_results.txt")
print(f"Total time: {time.time()-t0:.1f}s", flush=True)
