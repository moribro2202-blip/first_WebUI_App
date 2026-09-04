"""
Model v2: IDM/JRDB指数を使ったモデル比較
Market<=10フィルタ固定、スコアリングを変えて比較

Models:
  M0: Baseline (自作: jockey+horse+dist+surface+venue+trend)
  M1: IDMのみ (JRDBスピード指数をそのままスコアに)
  M2: 総合指数のみ (IDM+騎手+情報)
  M3: IDM + 自作特徴量
  M4: 総合指数 + 脚質補正
  M5: IDM + 馬場状態適性
  M6: IDM + 馬体重変化
  M7: Full combined (IDM + 脚質 + 馬場 + 体重 + 自作)
  M8: IDM + コーナー通過順(先行力)
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()

# Load entries with IDM data
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

# Load results with weight and corners
result_cache = defaultdict(list)
for row in db.execute('''SELECT race_id, horse_number, finish_position, finish_time,
                         horse_id, horse_weight, horse_weight_diff, corner_positions
                         FROM results WHERE finish_position IS NOT NULL
                         ORDER BY race_id, finish_position''').fetchall():
    result_cache[row[0]].append({
        'hn': row[1], 'fp': row[2], 'time': row[3], 'hid': row[4],
        'weight': row[5], 'weight_diff': row[6], 'corners': row[7]
    })

# Load race conditions
race_cond = {}
for row in db.execute('SELECT race_id, track_condition, weather FROM races').fetchall():
    race_cond[row[0]] = {'track': row[1], 'weather': row[2]}

# Load trio odds
tc = defaultdict(dict)
for rid, combo, odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    tc[rid][combo] = odds

# Load win odds
win_odds_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz:
        win_odds_cache[rid] = {int(r[0]):r[1] for r in oz}

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

# Build training stats
def build_train(train_start, train_end):
    jc = defaultdict(lambda:{'r':0,'w':0})
    hr = defaultdict(list)
    # Track condition performance per horse
    track_perf = defaultdict(lambda: defaultdict(list))  # hid -> track_cond -> [fp]
    # Corner/running style stats per horse
    run_stats = defaultdict(list)  # hid -> [avg_corner_position]

    for rid, rd, vc, sf, dt in races_raw:
        if rd < train_start or rd >= train_end: continue
        cond = race_cond.get(rid, {})
        track = cond.get('track', '良')
        for res in result_cache.get(rid, []):
            hn, fp, hid = res['hn'], res['fp'], res['hid']
            ent = entry_cache.get(rid, {}).get(hn, {})
            jn = ent.get('jockey', '')
            if jn:
                jc[jn]['r'] += 1
                if fp == 1: jc[jn]['w'] += 1
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'weight':res.get('weight'),'weight_diff':res.get('weight_diff')})
                if len(hr[hid]) > 30: hr[hid] = hr[hid][-30:]
                if track: track_perf[hid][track].append(fp)
                # Corner stats
                corners = res.get('corners')
                if corners:
                    parts = corners.split('-')
                    try:
                        first_corner = int(parts[0])
                        run_stats[hid].append(first_corner)
                        if len(run_stats[hid]) > 10: run_stats[hid] = run_stats[hid][-10:]
                    except: pass

    return jc, hr, track_perf, run_stats

# Score functions
def score_m0(h, rid, vc, sf, dt, jc, hr, **kw):
    """M0: Baseline"""
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

def score_m1(h, rid, vc, sf, dt, **kw):
    """M1: IDMのみ"""
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    return idm if idm and idm > 0 else 50.0

def score_m2(h, rid, vc, sf, dt, **kw):
    """M2: 総合指数のみ"""
    ent = entry_cache.get(rid,{}).get(h,{})
    total = ent.get('total')
    return total if total and total > 0 else 50.0

def score_m3(h, rid, vc, sf, dt, jc, hr, **kw):
    """M3: IDM + 自作特徴量"""
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    base_idm = idm if idm and idm > 0 else 50.0
    # Add subset of hand-crafted features (lighter weight)
    hid = ent.get('hid',''); jn = ent.get('jockey','')
    bonus = 0
    if hid and hid in hr:
        rc = hr[hid]
        dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
        if len(dr) >= 2: bonus += (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:])) * 1.0
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2: bonus += (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:])) * 1.0
        if len(rc) >= 3:
            l3 = [r['fp'] for r in rc[-3:]]
            if l3[-1] < l3[0]: bonus += (l3[0]-l3[-1]) * 0.5
    return base_idm + bonus

def score_m4(h, rid, vc, sf, dt, **kw):
    """M4: 総合指数 + 脚質補正"""
    ent = entry_cache.get(rid,{}).get(h,{})
    total = ent.get('total')
    base = total if total and total > 0 else 50.0
    rs = ent.get('run_style', '')
    # 先行有利バイアス
    rs_bonus = {'逃げ': 1.5, '先行': 1.0, '好位差し': 0.5, '差し': 0, '追込': -0.5, '自在': 0.5, '後方': -1.0}.get(rs, 0)
    return base + rs_bonus

def score_m5(h, rid, vc, sf, dt, track_perf, **kw):
    """M5: IDM + 馬場状態適性"""
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    base = idm if idm and idm > 0 else 50.0
    hid = ent.get('hid','')
    cond = race_cond.get(rid, {})
    track = cond.get('track', '良')
    tb = 0
    if hid and hid in track_perf and track in track_perf[hid]:
        results = track_perf[hid][track]
        if len(results) >= 3:
            avg = sum(results) / len(results)
            tb = (6 - avg) * 2.0  # good track perf = bonus
    return base + tb

def score_m6(h, rid, vc, sf, dt, hr, **kw):
    """M6: IDM + 馬体重変化"""
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    base = idm if idm and idm > 0 else 50.0
    hid = ent.get('hid','')
    wb = 0
    if hid and hid in hr:
        rc = hr[hid]
        # Check last weight_diff
        recent_w = [r for r in rc[-3:] if r.get('weight_diff') is not None]
        if recent_w:
            last_diff = recent_w[-1]['weight_diff']
            # Large weight change is bad
            if abs(last_diff) > 10: wb = -2.0
            elif abs(last_diff) <= 4: wb = 1.0  # stable = good
    return base + wb

def score_m7(h, rid, vc, sf, dt, jc, hr, track_perf, run_stats, **kw):
    """M7: Full combined"""
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    base = idm if idm and idm > 0 else 50.0
    rider = ent.get('rider')
    rider_b = rider if rider and rider > 0 else 0
    hid = ent.get('hid','')

    # Track condition
    cond = race_cond.get(rid, {})
    track = cond.get('track', '良')
    track_b = 0
    if hid and hid in track_perf and track in track_perf[hid]:
        results = track_perf[hid][track]
        if len(results) >= 3:
            avg = sum(results) / len(results)
            track_b = (6 - avg) * 1.5

    # Run style
    rs = ent.get('run_style', '')
    rs_b = {'逃げ': 1.0, '先行': 0.5, '好位差し': 0.3, '差し': 0, '追込': -0.3, '自在': 0.3, '後方': -0.5}.get(rs, 0)

    # Weight stability
    wb = 0
    if hid and hid in hr:
        rc = hr[hid]
        recent_w = [r for r in rc[-3:] if r.get('weight_diff') is not None]
        if recent_w:
            last_diff = recent_w[-1]['weight_diff']
            if abs(last_diff) > 10: wb = -1.5
            elif abs(last_diff) <= 4: wb = 0.5

    # Distance/surface fit from past
    fit_b = 0
    if hid and hid in hr:
        rc = hr[hid]
        dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
        if len(dr) >= 2: fit_b += (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:])) * 0.8
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2: fit_b += (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:])) * 0.8

    return base + rider_b + track_b + rs_b + wb + fit_b

def score_m8(h, rid, vc, sf, dt, run_stats, **kw):
    """M8: IDM + 先行力"""
    ent = entry_cache.get(rid,{}).get(h,{})
    idm = ent.get('idm')
    base = idm if idm and idm > 0 else 50.0
    hid = ent.get('hid','')
    fb = 0
    if hid and hid in run_stats:
        positions = run_stats[hid]
        if len(positions) >= 3:
            avg_pos = sum(positions) / len(positions)
            # Lower avg corner position = front runner = bonus
            if avg_pos <= 3: fb = 3.0
            elif avg_pos <= 5: fb = 1.5
            elif avg_pos <= 8: fb = 0
            else: fb = -1.0
    return base + fb

MODELS = {
    'M0: Baseline(self)': score_m0,
    'M1: IDM only': score_m1,
    'M2: TotalIdx only': score_m2,
    'M3: IDM+self feat': score_m3,
    'M4: Total+RunStyle': score_m4,
    'M5: IDM+TrackCond': score_m5,
    'M6: IDM+WeightChg': score_m6,
    'M7: Full Combined': score_m7,
    'M8: IDM+FrontRun': score_m8,
}

ALPHAS = [0.30, 0.40, 0.50, 0.60, 0.70]
beta = 1.03; scale = 0.15; max_odds = 10

out = open(r'C:\Users\moribro2201\Desktop\model_v2_idm_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s + '\n')

p('=' * 130)
p('=== Model v2: IDM/JRDB Index Comparison (Market<=10 filter) ===')
p('=' * 130)

for model_name, score_fn in MODELS.items():
    p(f'\n--- {model_name} ---')
    p(f'  {"alpha":>6} {"Total":>7} {"R":>5} {"Hits":>5} | {"2021":>12} {"2022":>12} {"2023":>12} {"2024":>12} {"2025":>12} {"2026":>12}')
    p(f'  {"-"*105}')

    for alpha in ALPHAS:
        yearly = {ty: {'b':0,'r':0,'h':0,'c':0} for ty in TY}

        for ty in TY:
            jc, hr, track_perf, run_stats = build_train(f'{ty-1}-01-01', f'{ty}-01-01')

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
                early = [om[h] for h in hl]
                trio = tc.get(rid, {})

                sc = [score_fn(h, rid, vc, sf, dt, jc=jc, hr=hr, track_perf=track_perf, run_stats=run_stats) for h in hl]
                mp = softmax(sc, scale); mkp = mktp(early, beta)
                bp = blendf(mp, mkp, alpha)
                rk = sorted(range(len(hl)), key=lambda i: -bp[i])
                top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
                combo = f'{top[0]}-{top[1]}-{top[2]}'
                ov = trio.get(combo, 0)
                if ov <= 0 or ov > max_odds: continue

                hit = frozenset(top) == frozenset(t3[:3])
                pay = B * ov if hit else 0
                yearly[ty]['b'] += B; yearly[ty]['c'] += 1
                yearly[ty]['r'] += pay
                if hit: yearly[ty]['h'] += 1

        tb = sum(v['b'] for v in yearly.values())
        tr = sum(v['r'] for v in yearly.values())
        total_rr = tr/tb*100 if tb > 0 else 0
        total_rc = sum(v['c'] for v in yearly.values())
        total_hits = sum(v['h'] for v in yearly.values())
        parts = []
        for ty in TY:
            s = yearly[ty]
            if s['b'] > 0:
                rr = s['r']/s['b']*100
                parts.append(f'{rr:>5.1f}%({s["c"]:>3}R)')
            else:
                parts.append(f'       ---')
        p(f'  {alpha:>5.2f} {total_rr:>6.1f}% {total_rc:>5} {total_hits:>5} | {" ".join(parts)}')

    print(f"  {model_name} done.", flush=True)

# Summary
p('\n' + '=' * 130)
p('=== Summary: Best alpha per model ===')
p('=' * 130)
p()
p(f'  {"Model":>22} {"BestA":>6} {"RR":>7} {"R":>5} {"Hit":>4} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
p(f'  {"-"*95}')

for model_name, score_fn in MODELS.items():
    best_rr = -1; best_alpha = 0; best_yearly = None; best_rc = 0; best_hits = 0
    for alpha in ALPHAS:
        yearly_rrs = []; tb_all = 0; tr_all = 0; hits_all = 0; rc_all = 0
        for ty in TY:
            jc, hr, track_perf, run_stats = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
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
                sc = [score_fn(h, rid, vc, sf, dt, jc=jc, hr=hr, track_perf=track_perf, run_stats=run_stats) for h in hl]
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
            rr = tr/tb*100 if tb > 0 else 0
            yearly_rrs.append(rr); tb_all += tb; tr_all += tr; hits_all += hits; rc_all += rc
        total_rr = tr_all/tb_all*100 if tb_all > 0 else 0
        if total_rr > best_rr:
            best_rr = total_rr; best_alpha = alpha; best_yearly = yearly_rrs; best_rc = rc_all; best_hits = hits_all

    yr_str = ' '.join(f'{r:>6.1f}%' for r in best_yearly)
    p(f'  {model_name:>22} {best_alpha:>5.2f} {best_rr:>6.1f}% {best_rc:>5} {best_hits:>4} | {yr_str}')

db.close(); out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\model_v2_idm_results.txt", flush=True)
