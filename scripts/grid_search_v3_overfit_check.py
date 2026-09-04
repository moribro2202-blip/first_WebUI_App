"""
過学習検証スクリプト
1. Leave-one-year-out: 5年で最適パラメータ探索 → 残り1年でテスト
2. Half-period: 前半3年で探索 → 後半3年でテスト（逆も）
3. 月別ブレイクダウン: トップ戦略の月別安定性
4. 近傍安定性: トップ設定の周辺パラメータの成績
"""
import sqlite3, math, time
from collections import defaultdict

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

ALPHAS = [0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
BETAS = [1.00, 1.03, 1.10]
SCALES = [0.05, 0.10, 0.15, 0.20, 0.30]
LOOKBACKS = [1, 2]
BUDGET = 10000
TEST_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]

MIN_TOP3_PROBS = [0.0, 0.45, 0.50, 0.55, 0.60]
DIVERGENCE_MODES = [-1, 0, 1]
MAX_TRIO_ODDS = [10, 15, 20, 50, 9999]
MAX_HORSES_LIST = [8, 10, 12, 14, 99]
MIN_TOP1_PROBS = [0.0, 0.20, 0.25, 0.30]

base_combos = len(ALPHAS) * len(BETAS) * len(SCALES) * len(LOOKBACKS)
filter_combos = len(MIN_TOP3_PROBS) * len(DIVERGENCE_MODES) * len(MAX_TRIO_ODDS) * len(MAX_HORSES_LIST) * len(MIN_TOP1_PROBS)
total_combos = base_combos * filter_combos
print(f"Base: {base_combos} x Filters: {filter_combos} = {total_combos:,} total", flush=True)

# === Step 1: データ読み込み ===
t0 = time.time()
print("Loading data...", flush=True)
races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

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
            mkt_top3 = set(sorted(hl, key=lambda h: om[h])[:3])
            # Extract month for monthly breakdown
            month = rd[5:7] if len(rd) >= 7 else '??'
            rd_list.append((hl, sc, early, om, t3_set, trio, mkt_top3, len(hl), month))

        race_data[(lb, test_year)] = rd_list
        print(f"  LB={lb} Year={test_year}: {len(rd_list)} races", flush=True)

print(f"Precomputation done ({time.time()-t0:.1f}s)", flush=True)
db.close()

# === Step 3: 全コンボの年別RRを計算 ===
print(f"\nComputing all yearly RR ({total_combos:,} combos)...", flush=True)

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

MIN_RACES = 30
t1 = time.time()
base_count = 0

# Store: list of (params_tuple, yearly_rr_list, yearly_bet_list, yearly_ret_list, yearly_races_list, monthly_data)
# For memory efficiency, only store yearly_rr and params
all_results = []  # (params_idx, yearly_rr[6], yearly_races[6])
params_list = []  # (lb, alpha, beta, scale, min_t3p, div, max_odds, max_h, min_t1p)

# Also store monthly data for top candidates
# monthly_detail[(lb,alpha,beta,scale)] = {year: {month: (bet, ret, hits, races)}}
monthly_store = {}

for lb in LOOKBACKS:
    for alpha in ALPHAS:
        for beta in BETAS:
            for scale in SCALES:
                base_count += 1
                race_metrics = {y: [] for y in TEST_YEARS}
                monthly_metrics = {y: defaultdict(list) for y in TEST_YEARS}

                for test_year in TEST_YEARS:
                    rd_list = race_data[(lb, test_year)]
                    for hl, sc, early, om, t3_set, trio, mkt_top3, num_h, month in rd_list:
                        n = len(hl)
                        mp = softmax(sc, scale)
                        mkp = mktp(early, beta)
                        if alpha <= 0.001: bp = mkp
                        elif alpha >= 0.999: bp = mp
                        else: bp = blendf(mp, mkp, alpha)
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
                        metric = (hit, payout, top3_prob, top1_prob, div_count, odds_val, num_h)
                        race_metrics[test_year].append(metric)
                        monthly_metrics[test_year][month].append(metric)

                monthly_store[(lb, alpha, beta, scale)] = monthly_metrics

                for min_t3p in MIN_TOP3_PROBS:
                    for div_mode in DIVERGENCE_MODES:
                        for max_odds in MAX_TRIO_ODDS:
                            for max_h in MAX_HORSES_LIST:
                                for min_t1p in MIN_TOP1_PROBS:
                                    yearly_rr = []
                                    yearly_races = []
                                    skip = False
                                    for test_year in TEST_YEARS:
                                        tb = 0; tr = 0; rc = 0
                                        for hit, payout, t3p, t1p, div_n, todds, nh in race_metrics[test_year]:
                                            if t3p < min_t3p: continue
                                            if min_t1p > 0 and t1p < min_t1p: continue
                                            if div_mode == 0 and div_n > 0: continue
                                            if div_mode == 1 and div_n == 0: continue
                                            if todds > max_odds: continue
                                            if nh > max_h: continue
                                            tb += BUDGET; rc += 1
                                            if hit: tr += payout
                                        if rc < MIN_RACES:
                                            skip = True; break
                                        yearly_rr.append(tr/tb*100 if tb > 0 else 0)
                                        yearly_races.append(rc)
                                    if skip: continue

                                    pidx = len(params_list)
                                    params_list.append((lb, alpha, beta, scale, min_t3p, div_mode, max_odds, max_h, min_t1p))
                                    all_results.append((pidx, yearly_rr, yearly_races))

                if base_count % 20 == 0:
                    elapsed = time.time() - t1
                    eta = elapsed / base_count * (base_combos - base_count)
                    print(f"  Base {base_count}/{base_combos} ({elapsed:.0f}s, ETA {eta:.0f}s) results={len(all_results)}", flush=True)

print(f"Done ({time.time()-t1:.1f}s), {len(all_results)} valid combos", flush=True)

# === Step 4: 分析 ===
out = open(r'C:\Users\moribro2201\Desktop\overfit_check_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

div_labels = {-1: '全部', 0: '一致', 1: '乖離'}

p('='*120)
p('=== 過学習検証 ===')
p('='*120)

# --- 4A: Leave-One-Year-Out ---
p(f'\n{"="*120}')
p('=== 検証1: Leave-One-Year-Out交差検証 ===')
p(f'{"="*120}')
p('各年を1年ずつホールドアウトし、残り5年でベストパラメータを選び、ホールドアウト年でテスト')
p('過学習なら: ホールドアウト年のRRが大幅に低下する')
p()

for held_out_idx in range(6):
    held_year = TEST_YEARS[held_out_idx]
    # Find best combo by 5-year total RR (excluding held_out)
    best_rr = -1; best_idx = -1
    for pidx, yrr, yrc in all_results:
        other_bet = sum(yrc[i] for i in range(6) if i != held_out_idx) * BUDGET
        other_ret = sum(yrc[i] * BUDGET * yrr[i] / 100 for i in range(6) if i != held_out_idx)
        other_rr = other_ret / other_bet * 100 if other_bet > 0 else 0
        # Also require all 5 training years to have enough races
        if other_rr > best_rr:
            best_rr = other_rr; best_idx = pidx
            best_yrr = yrr; best_yrc = yrc

    params = params_list[best_idx]
    held_rr = best_yrr[held_out_idx]
    held_rc = best_yrc[held_out_idx]
    train_rrs = [best_yrr[i] for i in range(6) if i != held_out_idx]
    train_avg = sum(train_rrs) / len(train_rrs)

    p(f'  ホールドアウト: {held_year}')
    p(f'    学習5年の平均RR: {train_avg:.1f}% ({", ".join(f"{r:.0f}%" for r in train_rrs)})')
    p(f'    テスト年のRR:    {held_rr:.1f}% ({held_rc}R)')
    p(f'    パラメータ: LB={params[0]} α={params[1]} β={params[2]} SC={params[3]} T3P>={params[4]} Div={div_labels[params[5]]} MxO={params[6]} MxH={params[7]} T1P>={params[8]}')
    p()

# --- 4B: Half-Period Test ---
p(f'\n{"="*120}')
p('=== 検証2: 半期テスト ===')
p(f'{"="*120}')

for train_years, test_years_sub, label in [
    ([0,1,2], [3,4,5], '前半(2021-2023)で探索 → 後半(2024-2026)でテスト'),
    ([3,4,5], [0,1,2], '後半(2024-2026)で探索 → 前半(2021-2023)でテスト'),
]:
    best_rr = -1; best_idx = -1
    for pidx, yrr, yrc in all_results:
        tr_bet = sum(yrc[i] for i in train_years) * BUDGET
        tr_ret = sum(yrc[i] * BUDGET * yrr[i] / 100 for i in train_years)
        tr_rr = tr_ret / tr_bet * 100 if tr_bet > 0 else 0
        if tr_rr > best_rr:
            best_rr = tr_rr; best_idx = pidx
            best_yrr = yrr; best_yrc = yrc

    params = params_list[best_idx]
    test_rrs = [best_yrr[i] for i in test_years_sub]
    test_rcs = [best_yrc[i] for i in test_years_sub]
    test_bet = sum(test_rcs) * BUDGET
    test_ret = sum(rc * BUDGET * rr / 100 for rc, rr in zip(test_rcs, test_rrs))
    test_total_rr = test_ret / test_bet * 100 if test_bet > 0 else 0
    train_rrs_list = [best_yrr[i] for i in train_years]

    p(f'\n  {label}')
    p(f'    学習期間RR: {", ".join(f"{TEST_YEARS[i]}={r:.1f}%" for i, r in zip(train_years, train_rrs_list))}')
    p(f'    テスト期間RR: {", ".join(f"{TEST_YEARS[i]}={r:.1f}%" for i, r in zip(test_years_sub, test_rrs))}')
    p(f'    テスト期間 通算: {test_total_rr:.1f}%')
    p(f'    パラメータ: LB={params[0]} α={params[1]} β={params[2]} SC={params[3]} T3P>={params[4]} Div={div_labels[params[5]]} MxO={params[6]} MxH={params[7]} T1P>={params[8]}')

# --- 4C: 6年プラスの設定の月別ブレイクダウン ---
p(f'\n{"="*120}')
p('=== 検証3: トップ戦略の月別安定性 ===')
p(f'{"="*120}')

# Find the best 6-year-plus combo
best_6plus = []
for pidx, yrr, yrc in all_results:
    plus = sum(1 for r in yrr if r >= 100)
    total_bet = sum(yrc) * BUDGET
    total_ret = sum(rc * BUDGET * rr / 100 for rc, rr in zip(yrc, yrr))
    total_rr = total_ret / total_bet * 100 if total_bet > 0 else 0
    if plus >= 6:
        best_6plus.append((total_rr, pidx, yrr, yrc))

best_6plus.sort(key=lambda x: -x[0])
p(f'\n  6年連続プラスの設定: {len(best_6plus)}通り')

# Show monthly for top 3
for rank, (total_rr, pidx, yrr, yrc) in enumerate(best_6plus[:3]):
    params = params_list[pidx]
    lb, alpha, beta, scale = params[0], params[1], params[2], params[3]
    min_t3p, div_mode, max_odds, max_h, min_t1p = params[4], params[5], params[6], params[7], params[8]

    p(f'\n  --- #{rank+1}: 通算{total_rr:.1f}% LB={lb} α={alpha} β={beta} SC={scale} T3P>={min_t3p} Div={div_labels[div_mode]} MxO={max_odds} MxH={max_h} T1P>={min_t1p} ---')
    p(f'  年別: {" ".join(f"{TEST_YEARS[i]}={yrr[i]:.1f}%" for i in range(6))}')

    ms = monthly_store.get((lb, alpha, beta, scale))
    if not ms: continue

    header = f'\n    {"月":>4}'
    for y in TEST_YEARS: header += f'  {y:>10}'
    header += f'  {"全年平均":>8}'
    p(header)
    p('    ' + '-'*80)

    for m in ['01','02','03','04','05','06','07','08','09','10','11','12']:
        month_rrs = []
        line = f'  {m:>4}'
        for y in TEST_YEARS:
            metrics = ms[y].get(m, [])
            tb = 0; tr = 0; rc = 0
            for hit, payout, t3p, t1p, div_n, todds, nh in metrics:
                if t3p < min_t3p: continue
                if min_t1p > 0 and t1p < min_t1p: continue
                if div_mode == 0 and div_n > 0: continue
                if div_mode == 1 and div_n == 0: continue
                if todds > max_odds: continue
                if nh > max_h: continue
                tb += BUDGET; rc += 1
                if hit: tr += payout
            if rc > 0:
                rr = tr/tb*100
                month_rrs.append(rr)
                line += f' {rr:>5.0f}%({rc:>2})'
            else:
                line += f'  {"---":>10}'
        if month_rrs:
            avg = sum(month_rrs)/len(month_rrs)
            line += f'  {avg:>6.1f}%'
        p(line)

# --- 4D: 近傍安定性 ---
p(f'\n{"="*120}')
p('=== 検証4: パラメータ近傍の安定性 ===')
p(f'{"="*120}')
p('トップ設定の周辺パラメータも同様にプラスか？')

if best_6plus:
    top_rr, top_pidx, top_yrr, top_yrc = best_6plus[0]
    top_params = params_list[top_pidx]
    p(f'\n  基準: LB={top_params[0]} α={top_params[1]} β={top_params[2]} SC={top_params[3]} T3P>={top_params[4]} Div={div_labels[top_params[5]]} MxO={top_params[6]} MxH={top_params[7]} T1P>={top_params[8]}')
    p(f'  基準RR: {top_rr:.1f}%')

    # Check all combos with same filters but different base params
    p(f'\n  同じフィルタ条件で異なるベースパラメータ:')
    p(f'  {"LB":>2} {"α":>5} {"β":>5} {"SC":>5} | {"通算":>6} {"P年":>3} | {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
    p(f'  {"-"*90}')

    same_filter = []
    for pidx, yrr, yrc in all_results:
        pp = params_list[pidx]
        if pp[4:] == top_params[4:]:  # same filter params
            total_bet = sum(yrc) * BUDGET
            total_ret = sum(rc * BUDGET * rr / 100 for rc, rr in zip(yrc, yrr))
            total_rr_v = total_ret / total_bet * 100 if total_bet > 0 else 0
            plus = sum(1 for r in yrr if r >= 100)
            same_filter.append((total_rr_v, plus, pp, yrr))

    same_filter.sort(key=lambda x: -x[0])
    for rr_v, plus, pp, yrr in same_filter:
        marker = ' ◀' if pp == top_params else ''
        p(f'  {pp[0]:>2} {pp[1]:>5.2f} {pp[2]:>5.2f} {pp[3]:>5.2f} | {rr_v:>5.1f}% {plus:>3} | {" ".join(f"{r:>5.1f}%" for r in yrr)}{marker}')

    # Also check: same base params but different filters
    p(f'\n  同じベースパラメータで異なるフィルタ条件 (top 30):')
    p(f'  {"T3P":>4} {"Div":>4} {"MxO":>5} {"MxH":>3} {"T1P":>4} | {"通算":>6} {"P年":>3} | {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
    p(f'  {"-"*100}')

    same_base = []
    for pidx, yrr, yrc in all_results:
        pp = params_list[pidx]
        if pp[:4] == top_params[:4]:  # same base params
            total_bet = sum(yrc) * BUDGET
            total_ret = sum(rc * BUDGET * rr / 100 for rc, rr in zip(yrc, yrr))
            total_rr_v = total_ret / total_bet * 100 if total_bet > 0 else 0
            plus = sum(1 for r in yrr if r >= 100)
            same_base.append((total_rr_v, plus, pp, yrr))

    same_base.sort(key=lambda x: (-x[1], -x[0]))
    for rr_v, plus, pp, yrr in same_base[:30]:
        mo = f'{pp[6]}' if pp[6] < 9999 else '∞'
        mh = f'{pp[7]}' if pp[7] < 99 else '∞'
        marker = ' ◀' if pp == top_params else ''
        p(f'  {pp[4]:>.2f} {div_labels[pp[5]]:>4} {mo:>5} {mh:>3} {pp[8]:>.2f} | {rr_v:>5.1f}% {plus:>3} | {" ".join(f"{r:>5.1f}%" for r in yrr)}{marker}')

# --- 4E: フィルタ「一致+低配当」は構造的か？ ---
p(f'\n{"="*120}')
p('=== 検証5: 「一致+低配当」フィルタの安定性 ===')
p(f'{"="*120}')
p('フィルタ: 一致 + max_odds=10 を固定し、ベースパラメータを変えた場合の通算RR分布')

agree_low = []
for pidx, yrr, yrc in all_results:
    pp = params_list[pidx]
    if pp[5] == 0 and pp[6] == 10:  # 一致 + max_odds=10
        total_bet = sum(yrc) * BUDGET
        total_ret = sum(rc * BUDGET * rr / 100 for rc, rr in zip(yrc, yrr))
        total_rr_v = total_ret / total_bet * 100 if total_bet > 0 else 0
        plus = sum(1 for r in yrr if r >= 100)
        agree_low.append((total_rr_v, plus, pp, yrr, yrc))

agree_low.sort(key=lambda x: -x[0])
p(f'\n  「一致+MxO=10」の設定数: {len(agree_low)}')
if agree_low:
    rrs = [x[0] for x in agree_low]
    p(f'  通算RR: 最高{max(rrs):.1f}% 最低{min(rrs):.1f}% 平均{sum(rrs)/len(rrs):.1f}% 中央値{sorted(rrs)[len(rrs)//2]:.1f}%')
    prof = sum(1 for r in rrs if r >= 100)
    p(f'  通算プラス: {prof}/{len(agree_low)} ({prof/len(agree_low)*100:.1f}%)')
    plus6 = sum(1 for x in agree_low if x[1] >= 6)
    plus5 = sum(1 for x in agree_low if x[1] >= 5)
    plus4 = sum(1 for x in agree_low if x[1] >= 4)
    p(f'  6年プラス: {plus6}, 5年以上: {plus5}, 4年以上: {plus4}')

    p(f'\n  Top 20:')
    p(f'  {"#":>3} {"LB":>2} {"α":>5} {"β":>5} {"SC":>5} {"T3P":>4} {"MxH":>3} {"T1P":>4} | {"通算":>6} {"P年":>3} | {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
    p(f'  {"-"*110}')
    for i, (rr_v, plus, pp, yrr, yrc) in enumerate(agree_low[:20]):
        mh = f'{pp[7]}' if pp[7] < 99 else '∞'
        p(f'  {i+1:>3} {pp[0]:>2} {pp[1]:>5.2f} {pp[2]:>5.2f} {pp[3]:>5.2f} {pp[4]:>.2f} {mh:>3} {pp[8]:>.2f} | {rr_v:>5.1f}% {plus:>3} | {" ".join(f"{r:>5.1f}%" for r in yrr)}')

out.close()
print(f"\nDone! Results: C:\\Users\\moribro2201\\Desktop\\overfit_check_results.txt")
print(f"Total time: {time.time()-t0:.1f}s", flush=True)
