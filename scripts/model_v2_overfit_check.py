"""
M7 (Full Combined) の過学習検証
1. Leave-One-Year-Out: 5年でベストα選択 → 残り1年テスト
2. Half-Period: 前半3年→後半3年、逆も
3. 全αで年別安定性確認
4. M0/M2/M7の3モデル横断比較
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()

entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('''SELECT horse_number, horse_id, jockey_name, idm, total_index,
                       rider_index, run_style, distance_aptitude
                       FROM entries WHERE race_id=?''', (rid,)).fetchall()
    if es:
        entry_cache[rid] = {}
        for e in es:
            entry_cache[rid][e[0]] = {
                'hid': e[1], 'jockey': e[2], 'idm': e[3], 'total': e[4],
                'rider': e[5], 'run_style': e[6], 'dist_apt': e[7]
            }

result_cache = defaultdict(list)
for row in db.execute('''SELECT race_id, horse_number, finish_position, finish_time,
                         horse_id, horse_weight, horse_weight_diff, corner_positions
                         FROM results WHERE finish_position IS NOT NULL
                         ORDER BY race_id, finish_position''').fetchall():
    result_cache[row[0]].append({
        'hn': row[1], 'fp': row[2], 'hid': row[4],
        'weight': row[5], 'weight_diff': row[6], 'corners': row[7]
    })

race_cond = {}
for row in db.execute('SELECT race_id, track_condition FROM races').fetchall():
    race_cond[row[0]] = row[1]

tc = defaultdict(dict)
for rid, combo, odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    tc[rid][combo] = odds

win_odds_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds_cache[rid] = {int(r[0]):r[1] for r in oz}

TY = [2021,2022,2023,2024,2025,2026]; B = 10000
print("Data loaded.", flush=True)

def softmax(sc, scale):
    s = [(x-50)*scale for x in sc]; mx = max(s); e = [math.exp(x-mx) for x in s]; t = sum(e)
    return [x/t for x in e]
def mktp(odds, beta):
    inv = [1/o if o > 0 else 0 for o in odds]; s = sum(inv)
    if s == 0: return [1/len(odds)]*len(odds)
    raw = [i/s for i in inv]; pw = [p_**beta for p_ in raw]; ps = sum(pw)
    return [p_/ps for p_ in pw]
def blendf(m, mk, alpha):
    bl = [math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s = sum(bl); return [p_/s for p_ in bl]

def build_train(train_start, train_end):
    jc = defaultdict(lambda:{'r':0,'w':0})
    hr = defaultdict(list)
    track_perf = defaultdict(lambda: defaultdict(list))
    run_stats = defaultdict(list)
    for rid, rd, vc, sf, dt in races_raw:
        if rd < train_start or rd >= train_end: continue
        track = race_cond.get(rid, '良')
        for res in result_cache.get(rid, []):
            hn, fp, hid = res['hn'], res['fp'], res['hid']
            ent = entry_cache.get(rid, {}).get(hn, {})
            jn = ent.get('jockey', '')
            if jn:
                jc[jn]['r'] += 1
                if fp == 1: jc[jn]['w'] += 1
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,
                               'weight':res.get('weight'),'weight_diff':res.get('weight_diff')})
                if len(hr[hid]) > 30: hr[hid] = hr[hid][-30:]
                if track: track_perf[hid][track].append(fp)
                corners = res.get('corners')
                if corners:
                    parts = corners.split('-')
                    try:
                        run_stats[hid].append(int(parts[0]))
                        if len(run_stats[hid]) > 10: run_stats[hid] = run_stats[hid][-10:]
                    except: pass
    return jc, hr, track_perf, run_stats

# Score functions
def score_m0(h, rid, vc, sf, dt, jc, hr, **kw):
    base = 50.0
    ent = entry_cache.get(rid,{}).get(h,{})
    hid = ent.get('hid',''); jn = ent.get('jockey','')
    jb = 0
    if jn and jn in jc and jc[jn]['r'] >= 20:
        jb = (jc[jn]['w']/jc[jn]['r'] - 0.08) * 50
    hb = db_ = sb = vb = tb = 0
    if hid and hid in hr:
        rc = hr[hid]
        if len(rc) >= 2: hb = (6-sum(r['fp'] for r in rc[-5:])/len(rc[-5:])) * 2
        dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
        if len(dr) >= 2: db_ = (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:])) * 1.5
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2: sb = (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:])) * 1.5
        vr = [r for r in rc if r['venue'] == vc]
        if len(vr) >= 2: vb = (6-sum(r['fp'] for r in vr[-5:])/len(vr[-5:])) * 1.0
        if len(rc) >= 3:
            l3 = [r['fp'] for r in rc[-3:]]
            if l3[-1] < l3[0]: tb = (l3[0]-l3[-1]) * 0.8
    return base + jb + hb + db_ + sb + vb + tb

def score_m2(h, rid, vc, sf, dt, **kw):
    ent = entry_cache.get(rid,{}).get(h,{})
    total = ent.get('total')
    return total if total and total > 0 else 50.0

def score_m7(h, rid, vc, sf, dt, jc, hr, track_perf, run_stats, **kw):
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    base = idm if idm and idm > 0 else 50.0
    rider = ent.get('rider')
    rider_b = rider if rider and rider > 0 else 0
    hid = ent.get('hid','')
    track = race_cond.get(rid, '良')
    track_b = 0
    if hid and hid in track_perf and track in track_perf[hid]:
        results = track_perf[hid][track]
        if len(results) >= 3:
            track_b = (6 - sum(results)/len(results)) * 1.5
    rs = ent.get('run_style', '')
    rs_b = {'逃げ':1.0,'先行':0.5,'好位差し':0.3,'差し':0,'追込':-0.3,'自在':0.3,'後方':-0.5}.get(rs, 0)
    wb = 0
    if hid and hid in hr:
        rc = hr[hid]
        recent_w = [r for r in rc[-3:] if r.get('weight_diff') is not None]
        if recent_w:
            last_diff = recent_w[-1]['weight_diff']
            if abs(last_diff) > 10: wb = -1.5
            elif abs(last_diff) <= 4: wb = 0.5
    fit_b = 0
    if hid and hid in hr:
        rc = hr[hid]
        dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
        if len(dr) >= 2: fit_b += (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:])) * 0.8
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2: fit_b += (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:])) * 0.8
    return base + rider_b + track_b + rs_b + wb + fit_b

MODELS = {'M0': score_m0, 'M2': score_m2, 'M7': score_m7}
ALPHAS = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
beta = 1.03; scale = 0.15; max_odds = 10

# Pre-compute yearly results for all (model, alpha, year)
print("Pre-computing all (model, alpha, year) results...", flush=True)
# cache: (model_name, alpha, year) -> {'b','r','h','c'}
sim_cache = {}

for model_name, score_fn in MODELS.items():
    for alpha in ALPHAS:
        for ty in TY:
            jc, hr, tp, rs = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
            tb = 0; tr = 0; hits = 0; rc = 0
            for rid, rd, vc, sf, dt in races_raw:
                if rd < f'{ty}-01-01' or rd >= f'{ty+1}-01-01': continue
                res_list = result_cache.get(rid, [])
                if len(res_list) < 5: continue
                t3 = [r['hn'] for r in res_list if r['fp'] <= 3]
                if len(t3) < 3: continue
                om = win_odds_cache.get(rid)
                if not om: continue
                hl = sorted(om.keys())
                if len(hl) < 5: continue
                early = [om[h] for h in hl]; trio = tc.get(rid, {})
                sc = [score_fn(h, rid, vc, sf, dt, jc=jc, hr=hr, track_perf=tp, run_stats=rs) for h in hl]
                mp = softmax(sc, scale); mkp = mktp(early, beta)
                bp = blendf(mp, mkp, alpha)
                rk = sorted(range(len(hl)), key=lambda i: -bp[i])
                top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
                combo = f'{top[0]}-{top[1]}-{top[2]}'
                ov = trio.get(combo, 0)
                if ov <= 0 or ov > max_odds: continue
                hit = frozenset(top) == frozenset(t3[:3])
                tb += B; tr += B*ov if hit else 0; rc += 1
                if hit: hits += 1
            sim_cache[(model_name, alpha, ty)] = {'b': tb, 'r': tr, 'h': hits, 'c': rc}
    print(f"  {model_name} done.", flush=True)

db.close()

def get_rr(model, alpha, year):
    d = sim_cache[(model, alpha, year)]
    return d['r']/d['b']*100 if d['b'] > 0 else 0

def get_total_rr(model, alpha, years):
    tb = sum(sim_cache[(model, alpha, y)]['b'] for y in years)
    tr = sum(sim_cache[(model, alpha, y)]['r'] for y in years)
    return tr/tb*100 if tb > 0 else 0

out = open(r'C:\Users\moribro2201\Desktop\model_v2_overfit_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s + '\n')

# === Test 1: Leave-One-Year-Out ===
p('=' * 120)
p('=== Test 1: Leave-One-Year-Out (5年でベストα → 1年テスト) ===')
p('=' * 120)
p()

for model_name in ['M0', 'M2', 'M7']:
    p(f'--- {model_name} ---')
    p(f'  {"Held":>4} {"TrainBestA":>10} {"Train5yRR":>9} {"TestRR":>7} {"TestR":>5} | {"Train years detail"}')
    p(f'  {"-"*90}')

    held_results = []
    for held_idx in range(6):
        held_year = TY[held_idx]
        train_years = [y for y in TY if y != held_year]
        # Find best alpha on train years
        best_rr = -1; best_a = 0
        for alpha in ALPHAS:
            rr = get_total_rr(model_name, alpha, train_years)
            if rr > best_rr: best_rr = rr; best_a = alpha
        # Test on held year
        test_rr = get_rr(model_name, best_a, held_year)
        test_d = sim_cache[(model_name, best_a, held_year)]
        train_detail = ' '.join(f'{get_rr(model_name, best_a, y):>5.1f}%' for y in train_years)
        p(f'  {held_year:>4} a={best_a:.2f}      {best_rr:>7.1f}%  {test_rr:>6.1f}% {test_d["c"]:>5} | {train_detail}')
        held_results.append(test_rr)

    avg_test = sum(held_results) / len(held_results)
    plus = sum(1 for r in held_results if r >= 100)
    p(f'  Avg test RR: {avg_test:.1f}%, Plus years: {plus}/6')
    p()

# === Test 2: Half-Period ===
p('=' * 120)
p('=== Test 2: Half-Period (3年→3年) ===')
p('=' * 120)
p()

for model_name in ['M0', 'M2', 'M7']:
    p(f'--- {model_name} ---')
    for train_idx, test_idx, label in [
        ([0,1,2], [3,4,5], '2021-23 -> 2024-26'),
        ([3,4,5], [0,1,2], '2024-26 -> 2021-23'),
    ]:
        train_years = [TY[i] for i in train_idx]
        test_years = [TY[i] for i in test_idx]
        # Find best alpha on train
        best_rr = -1; best_a = 0
        for alpha in ALPHAS:
            rr = get_total_rr(model_name, alpha, train_years)
            if rr > best_rr: best_rr = rr; best_a = alpha
        # Test
        test_rr = get_total_rr(model_name, best_a, test_years)
        train_detail = ' '.join(f'{get_rr(model_name, best_a, y):>5.1f}%' for y in train_years)
        test_detail = ' '.join(f'{get_rr(model_name, best_a, y):>5.1f}%' for y in test_years)
        p(f'  {label}: a={best_a:.2f} Train={best_rr:.1f}% Test={test_rr:.1f}%')
        p(f'    Train: {train_detail}')
        p(f'    Test:  {test_detail}')
    p()

# === Test 3: Fixed alpha stability ===
p('=' * 120)
p('=== Test 3: Fixed Alpha Stability (M7) ===')
p('=' * 120)
p()
p(f'  {"alpha":>6} {"Total":>7} {"PlusYr":>6} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
p(f'  {"-"*75}')
for alpha in ALPHAS:
    yearly = [get_rr('M7', alpha, y) for y in TY]
    total = get_total_rr('M7', alpha, TY)
    plus = sum(1 for r in yearly if r >= 100)
    yr_str = ' '.join(f'{r:>6.1f}%' for r in yearly)
    p(f'  {alpha:>5.2f} {total:>6.1f}% {plus:>4}/6  | {yr_str}')

# === Test 4: Model comparison at fixed alpha ===
p()
p('=' * 120)
p('=== Test 4: Model Comparison at Fixed Alpha=0.50 ===')
p('=' * 120)
p()
p(f'  {"Model":>5} {"Total":>7} {"PlusYr":>6} {"R":>5} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
p(f'  {"-"*80}')
for model_name in ['M0', 'M2', 'M7']:
    alpha = 0.50
    yearly = [get_rr(model_name, alpha, y) for y in TY]
    total = get_total_rr(model_name, alpha, TY)
    plus = sum(1 for r in yearly if r >= 100)
    total_rc = sum(sim_cache[(model_name, alpha, y)]['c'] for y in TY)
    yr_str = ' '.join(f'{r:>6.1f}%' for r in yearly)
    p(f'  {model_name:>5} {total:>6.1f}% {plus:>4}/6  {total_rc:>5} | {yr_str}')

# === Test 5: Robustness - how many alpha values give >105% for M7? ===
p()
p('=' * 120)
p('=== Test 5: Alpha Robustness (how many alphas give total > X%) ===')
p('=' * 120)
p()
for model_name in ['M0', 'M2', 'M7']:
    above_105 = sum(1 for a in ALPHAS if get_total_rr(model_name, a, TY) >= 105)
    above_108 = sum(1 for a in ALPHAS if get_total_rr(model_name, a, TY) >= 108)
    above_110 = sum(1 for a in ALPHAS if get_total_rr(model_name, a, TY) >= 110)
    best = max(get_total_rr(model_name, a, TY) for a in ALPHAS)
    worst = min(get_total_rr(model_name, a, TY) for a in ALPHAS)
    p(f'  {model_name}: best={best:.1f}% worst={worst:.1f}% | >=105%: {above_105}/{len(ALPHAS)} >=108%: {above_108}/{len(ALPHAS)} >=110%: {above_110}/{len(ALPHAS)}')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\model_v2_overfit_results.txt", flush=True)
