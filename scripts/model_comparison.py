"""
Model Comparison: Market<=10 filter fixed, scoring model varies
Models:
  M0: Baseline (jockey + horse + dist + surface + venue + trend)
  M1: + Speed Index (normalized finish time)
  M2: + Consistency (low variance bonus)
  M3: + Value Perf (actual finish vs market expectation)
  M4: + Age factor
  M5: + Sire performance on surface
  M6: + Rest days (interval between races)
  M7: Combined (all of above)
  M8: Reweighted (different weight balance)
"""
import sqlite3, math
from collections import defaultdict

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
ec = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: ec[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}
tc = defaultdict(dict)
for rid, combo, odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    tc[rid][combo] = odds

# Load all results with time, popularity, odds
all_results = db.execute("""
    SELECT r.race_id, r.horse_number, r.finish_position, r.finish_time,
           r.popularity, r.win_odds, r.horse_id
    FROM results r
    WHERE r.finish_position IS NOT NULL
    ORDER BY r.race_id, r.finish_position
""").fetchall()

# Build result lookup: race_id -> list of (hn, fp, time, pop, odds, hid)
result_lookup = defaultdict(list)
for rid, hn, fp, ft, pop, odds, hid in all_results:
    result_lookup[rid].append({'hn':hn,'fp':fp,'time':ft,'pop':pop,'odds':odds,'hid':hid})

# Load horse info
horse_info = {}
for row in db.execute("SELECT horse_id, birth_year, sex, sire FROM horses").fetchall():
    horse_info[row[0]] = {'birth_year': row[1], 'sex': row[2], 'sire': row[3]}

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

# Build training stats per model
def build_training(train_start, train_end):
    """Build all training features from train_start to train_end"""
    jc = defaultdict(lambda:{'r':0,'w':0})
    hr = defaultdict(list)  # horse_id -> [{fp, dist, surface, venue, time, pop, odds, date}]
    sire_perf = defaultdict(lambda: defaultdict(list))  # sire -> surface -> [fp]

    for rid, rd, vc, sf, dt in races_raw:
        if rd < train_start or rd >= train_end: continue
        for res in result_lookup.get(rid, []):
            hn, fp, ft, pop, odds, hid = res['hn'], res['fp'], res['time'], res['pop'], res['odds'], res['hid']
            ent = ec.get(rid, {}).get(hn, {})
            jn = ent.get('jockey', '')
            if jn:
                jc[jn]['r'] += 1
                if fp == 1: jc[jn]['w'] += 1
            if hid:
                entry = {'fp':fp, 'dist':dt, 'surface':sf, 'venue':vc, 'time':ft, 'pop':pop, 'odds':odds, 'date':rd}
                hr[hid].append(entry)
                if len(hr[hid]) > 30: hr[hid] = hr[hid][-30:]
                # Sire performance
                hi = horse_info.get(hid, {})
                sire = hi.get('sire', '')
                if sire: sire_perf[sire][sf].append(fp)

    # Compute speed index baselines: avg time per (venue, surface, distance)
    speed_baselines = defaultdict(list)
    for rid, rd, vc, sf, dt in races_raw:
        if rd < train_start or rd >= train_end: continue
        for res in result_lookup.get(rid, []):
            if res['time'] and res['time'] > 0 and res['fp'] <= 5:  # top 5 finishers
                speed_baselines[(vc, sf, dt)].append(res['time'])

    speed_avg = {}
    for key, times in speed_baselines.items():
        if len(times) >= 10:
            speed_avg[key] = sum(times) / len(times)

    return jc, hr, sire_perf, speed_avg

def score_m0(h, rid, vc, sf, dt, jc, hr, **kw):
    """M0: Baseline (current model)"""
    base = 50.0
    ent = ec.get(rid,{}).get(h,{})
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

def score_m1(h, rid, vc, sf, dt, jc, hr, speed_avg, **kw):
    """M1: + Speed Index"""
    base = score_m0(h, rid, vc, sf, dt, jc, hr)
    ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid','')
    si = 0
    if hid and hid in hr:
        rc = hr[hid]
        # Speed index: compare horse's time to baseline
        speed_entries = [r for r in rc[-5:] if r.get('time') and r['time'] > 0 and r.get('dist')]
        if len(speed_entries) >= 2:
            indices = []
            for r in speed_entries:
                key = (r.get('venue',''), r['surface'], r['dist'])
                avg = speed_avg.get(key)
                if avg and avg > 0:
                    # Negative = faster than average (good)
                    idx = (avg - r['time']) / avg * 100
                    indices.append(idx)
            if indices:
                si = sum(indices) / len(indices) * 3  # scale factor
    return base + si

def score_m2(h, rid, vc, sf, dt, jc, hr, **kw):
    """M2: + Consistency (low variance bonus)"""
    base = score_m0(h, rid, vc, sf, dt, jc, hr)
    ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid','')
    cb = 0
    if hid and hid in hr:
        rc = hr[hid]
        if len(rc) >= 4:
            fps = [r['fp'] for r in rc[-6:]]
            avg = sum(fps) / len(fps)
            var = sum((f-avg)**2 for f in fps) / len(fps)
            std = var ** 0.5
            # Low std + good avg = bonus
            if avg <= 5 and std <= 2: cb = (5 - avg) * (3 - std) * 1.0
    return base + cb

def score_m3(h, rid, vc, sf, dt, jc, hr, **kw):
    """M3: + Value Performance (actual vs expected from odds)"""
    base = score_m0(h, rid, vc, sf, dt, jc, hr)
    ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid','')
    vp = 0
    if hid and hid in hr:
        rc = hr[hid]
        val_entries = [r for r in rc[-5:] if r.get('pop') and r['pop'] > 0]
        if len(val_entries) >= 2:
            # How much better/worse than popularity ranking
            diffs = [r['pop'] - r['fp'] for r in val_entries]  # positive = outperformed
            vp = sum(diffs) / len(diffs) * 1.5
    return base + vp

def score_m4(h, rid, vc, sf, dt, jc, hr, race_date, **kw):
    """M4: + Age factor"""
    base = score_m0(h, rid, vc, sf, dt, jc, hr)
    ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid','')
    ab = 0
    if hid:
        hi = horse_info.get(hid, {})
        by = hi.get('birth_year', 0)
        if by and by > 0:
            try:
                race_year = int(race_date[:4])
                age = race_year - by
                # Optimal age is 3-5 for flat racing
                if 3 <= age <= 5: ab = 2.0
                elif age == 6: ab = 0.5
                elif age >= 7: ab = -1.0
            except: pass
    return base + ab

def score_m5(h, rid, vc, sf, dt, jc, hr, sire_perf, **kw):
    """M5: + Sire performance on surface"""
    base = score_m0(h, rid, vc, sf, dt, jc, hr)
    ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid','')
    sp = 0
    if hid:
        hi = horse_info.get(hid, {})
        sire = hi.get('sire', '')
        if sire and sire in sire_perf:
            surface_results = sire_perf[sire].get(sf, [])
            if len(surface_results) >= 30:
                avg_fp = sum(surface_results) / len(surface_results)
                win_rate = sum(1 for f in surface_results if f == 1) / len(surface_results)
                sp = (win_rate - 0.06) * 30  # 6% is average
    return base + sp

def score_m6(h, rid, vc, sf, dt, jc, hr, race_date, **kw):
    """M6: + Rest days"""
    base = score_m0(h, rid, vc, sf, dt, jc, hr)
    ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid','')
    rb = 0
    if hid and hid in hr:
        rc = hr[hid]
        if rc:
            last_date = rc[-1].get('date', '')
            if last_date and race_date:
                try:
                    from datetime import datetime
                    d1 = datetime.strptime(last_date, '%Y-%m-%d')
                    d2 = datetime.strptime(race_date, '%Y-%m-%d')
                    days = (d2 - d1).days
                    if 14 <= days <= 35: rb = 2.0    # ideal rest
                    elif 35 < days <= 60: rb = 1.0   # ok
                    elif 60 < days <= 90: rb = 0.0   # neutral
                    elif days > 180: rb = -2.0       # long layoff
                except: pass
    return base + rb

def score_m7(h, rid, vc, sf, dt, jc, hr, speed_avg, sire_perf, race_date, **kw):
    """M7: Combined (M1+M2+M3+M4+M5+M6 all together)"""
    s1 = score_m1(h, rid, vc, sf, dt, jc, hr, speed_avg=speed_avg) - 50
    s2 = score_m2(h, rid, vc, sf, dt, jc, hr) - 50
    s3 = score_m3(h, rid, vc, sf, dt, jc, hr) - 50
    s4 = score_m4(h, rid, vc, sf, dt, jc, hr, race_date=race_date) - 50
    s5 = score_m5(h, rid, vc, sf, dt, jc, hr, sire_perf=sire_perf) - 50
    s6 = score_m6(h, rid, vc, sf, dt, jc, hr, race_date=race_date) - 50
    return 50 + s1 + (s2 - score_m0(h, rid, vc, sf, dt, jc, hr) + 50) + \
           (s3 - score_m0(h, rid, vc, sf, dt, jc, hr) + 50) + \
           (s4 - score_m0(h, rid, vc, sf, dt, jc, hr) + 50) + \
           (s5 - score_m0(h, rid, vc, sf, dt, jc, hr) + 50) + \
           (s6 - score_m0(h, rid, vc, sf, dt, jc, hr) + 50)

def score_m8(h, rid, vc, sf, dt, jc, hr, speed_avg, **kw):
    """M8: Reweighted - more weight on speed, less on jockey"""
    base = 50.0
    ent = ec.get(rid,{}).get(h,{})
    hid = ent.get('hid',''); jn = ent.get('jockey','')
    jb = 0
    if jn and jn in jc and jc[jn]['r'] >= 20:
        jb = (jc[jn]['w']/jc[jn]['r'] - 0.08) * 25  # halved from 50
    hb = db_ = sb = vb = tb = si = 0
    if hid and hid in hr:
        rc = hr[hid]
        if len(rc) >= 2: hb = (6-sum(r['fp'] for r in rc[-5:])/len(rc[-5:])) * 3  # increased from 2
        dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
        if len(dr) >= 2: db_ = (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:])) * 2  # increased from 1.5
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2: sb = (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:])) * 2
        vr = [r for r in rc if r['venue'] == vc]
        if len(vr) >= 2: vb = (6-sum(r['fp'] for r in vr[-5:])/len(vr[-5:])) * 1.0
        if len(rc) >= 3:
            l3 = [r['fp'] for r in rc[-3:]]
            if l3[-1] < l3[0]: tb = (l3[0]-l3[-1]) * 1.2  # increased from 0.8
        # Speed index
        speed_entries = [r for r in rc[-5:] if r.get('time') and r['time'] > 0 and r.get('dist')]
        if len(speed_entries) >= 2:
            indices = []
            for r in speed_entries:
                key = (r.get('venue',''), r['surface'], r['dist'])
                avg = speed_avg.get(key)
                if avg and avg > 0:
                    idx = (avg - r['time']) / avg * 100
                    indices.append(idx)
            if indices:
                si = sum(indices) / len(indices) * 4  # strong weight
    return base + jb + hb + db_ + sb + vb + tb + si

MODELS = {
    'M0: Baseline': score_m0,
    'M1: +SpeedIdx': score_m1,
    'M2: +Consistency': score_m2,
    'M3: +ValuePerf': score_m3,
    'M4: +Age': score_m4,
    'M5: +SirePerf': score_m5,
    'M6: +RestDays': score_m6,
    'M7: Combined': score_m7,
    'M8: Reweighted': score_m8,
}

ALPHAS = [0.30, 0.40, 0.50, 0.60, 0.70]
beta = 1.03; scale = 0.15; max_odds = 10

out = open(r'C:\Users\moribro2201\Desktop\model_comparison_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s + '\n')

p('=' * 130)
p('=== Model Comparison: Market<=10 filter, varying scoring model ===')
p('=' * 130)

for model_name, score_fn in MODELS.items():
    p(f'\n--- {model_name} ---')
    p(f'  {"alpha":>6} {"Total":>7} {"R":>5} | {"2021":>12} {"2022":>12} {"2023":>12} {"2024":>12} {"2025":>12} {"2026":>12}')
    p(f'  {"-"*100}')

    for alpha in ALPHAS:
        yearly_stats = {ty: {'b':0,'r':0,'h':0,'c':0} for ty in TY}

        for ty in TY:
            train_start = f'{ty-1}-01-01'
            train_end = f'{ty}-01-01'
            jc, hr, sire_perf, speed_avg = build_training(train_start, train_end)

            for rid, rd, vc, sf, dt in races_raw:
                if rd < f'{ty}-01-01' or rd >= f'{ty+1}-01-01': continue
                res_list = result_lookup.get(rid, [])
                if len(res_list) < 5: continue
                t3 = [r['hn'] for r in res_list if r['fp'] <= 3]
                if len(t3) < 3: continue
                oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
                if not oz: continue
                om = {int(r[0]):r[1] for r in oz}; hl = sorted(om.keys())
                if len(hl) < 5: continue
                early = [om[h] for h in hl]
                trio = tc.get(rid, {})

                sc = [score_fn(h, rid, vc, sf, dt, jc=jc, hr=hr, speed_avg=speed_avg,
                              sire_perf=sire_perf, race_date=rd) for h in hl]
                mp = softmax(sc, scale); mkp = mktp(early, beta)
                bp = blendf(mp, mkp, alpha)
                rk = sorted(range(len(hl)), key=lambda i: -bp[i])
                top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
                combo = f'{top[0]}-{top[1]}-{top[2]}'
                ov = trio.get(combo, 0)
                if ov <= 0 or ov > max_odds: continue

                hit = frozenset(top) == frozenset(t3[:3])
                pay = B * ov if hit else 0
                yearly_stats[ty]['b'] += B; yearly_stats[ty]['c'] += 1
                yearly_stats[ty]['r'] += pay
                if hit: yearly_stats[ty]['h'] += 1

        tb = sum(v['b'] for v in yearly_stats.values())
        tr = sum(v['r'] for v in yearly_stats.values())
        total_rr = tr/tb*100 if tb > 0 else 0
        total_rc = sum(v['c'] for v in yearly_stats.values())
        parts = []
        for ty in TY:
            s = yearly_stats[ty]
            if s['b'] > 0:
                rr = s['r']/s['b']*100
                parts.append(f'{rr:>5.1f}%({s["c"]:>3}R)')
            else:
                parts.append(f'       ---')
        p(f'  {alpha:>5.2f} {total_rr:>6.1f}% {total_rc:>5} | {" ".join(parts)}')

    print(f"  {model_name} done.", flush=True)

# Summary table
p()
p('=' * 130)
p('=== Summary: Best alpha per model ===')
p('=' * 130)
p()
p(f'  {"Model":>20} {"BestA":>6} {"TotalRR":>8} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
p(f'  {"-"*85}')

# Re-run to find best alpha per model (already printed above, collect here)
# This is a simplified re-computation for the summary
for model_name, score_fn in MODELS.items():
    best_rr = -1; best_alpha = 0; best_yearly = None
    for alpha in ALPHAS:
        yearly_rrs = []
        tb_all = 0; tr_all = 0
        for ty in TY:
            jc, hr, sire_perf, speed_avg = build_training(f'{ty-1}-01-01', f'{ty}-01-01')
            tb = 0; tr = 0
            for rid, rd, vc, sf, dt in races_raw:
                if rd < f'{ty}-01-01' or rd >= f'{ty+1}-01-01': continue
                res_list = result_lookup.get(rid, [])
                if len(res_list) < 5: continue
                t3 = [r['hn'] for r in res_list if r['fp'] <= 3]
                if len(t3) < 3: continue
                oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
                if not oz: continue
                om = {int(r[0]):r[1] for r in oz}; hl = sorted(om.keys())
                if len(hl) < 5: continue
                early = [om[h] for h in hl]; trio = tc.get(rid, {})
                sc = [score_fn(h, rid, vc, sf, dt, jc=jc, hr=hr, speed_avg=speed_avg,
                              sire_perf=sire_perf, race_date=rd) for h in hl]
                mp = softmax(sc, scale); mkp = mktp(early, beta)
                bp = blendf(mp, mkp, alpha)
                rk = sorted(range(len(hl)), key=lambda i: -bp[i])
                top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
                combo = f'{top[0]}-{top[1]}-{top[2]}'
                ov = trio.get(combo, 0)
                if ov <= 0 or ov > max_odds: continue
                hit = frozenset(top) == frozenset(t3[:3])
                tb += B; tr += B * ov if hit else 0
            rr = tr/tb*100 if tb > 0 else 0
            yearly_rrs.append(rr)
            tb_all += tb; tr_all += tr
        total_rr = tr_all/tb_all*100 if tb_all > 0 else 0
        if total_rr > best_rr:
            best_rr = total_rr; best_alpha = alpha; best_yearly = yearly_rrs

    yr_str = ' '.join(f'{r:>6.1f}%' for r in best_yearly)
    p(f'  {model_name:>20} {best_alpha:>5.2f} {best_rr:>7.1f}% | {yr_str}')
    print(f"  Summary: {model_name} best={best_rr:.1f}% a={best_alpha}", flush=True)

db.close()
out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\model_comparison_results.txt", flush=True)
