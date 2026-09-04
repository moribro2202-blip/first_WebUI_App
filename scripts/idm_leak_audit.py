"""
IDMリーク監査
1. TYBファイル日付 vs レース日付の突き合わせ
2. IDMを1週間前のTYB値に差し替えてRRテスト
3. IDMをランダムシャッフルしてRRテスト（エッジがIDM由来か確認）
"""
import sqlite3, math, sys, os, glob, random
from collections import defaultdict
from itertools import permutations
sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

# === Audit 1: TYB file date vs race date ===
print("=== Audit 1: TYB file date vs race date ===", flush=True)

tyb_dir = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb\TYB'
tyb_files = sorted(glob.glob(os.path.join(tyb_dir, '*.txt')))

# Build map: race_id -> TYB file date
tyb_race_dates = {}  # race_id -> tyb_file_date
for fpath in tyb_files:
    fname = os.path.basename(fpath)
    # TYByymmdd.txt -> file_date = 20yy-mm-dd
    if not fname.startswith('TYB') or len(fname) < 12: continue
    yy = fname[3:5]; mm = fname[5:7]; dd = fname[7:9]
    try:
        file_date = f'20{yy}-{mm}-{dd}'
    except:
        continue
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 10: continue
            venue = line[0:2].decode('ascii','replace').strip()
            year = line[2:4].decode('ascii','replace').strip()
            kai = line[4:6].decode('ascii','replace').strip()
            race = line[6:8].decode('ascii','replace').strip()
            if venue and year and kai and race:
                race_id = f'{year}{venue}{kai}{race}'
                tyb_race_dates[race_id] = file_date

# Compare with actual race dates
race_dates = {}
for row in db.execute('SELECT race_id, race_date FROM races').fetchall():
    race_dates[row[0]] = row[1]

mismatch = 0; match = 0; total_checked = 0
future_leak = 0
examples = []
for race_id, tyb_date in tyb_race_dates.items():
    if race_id not in race_dates: continue
    actual_date = race_dates[race_id]
    total_checked += 1
    if tyb_date == actual_date:
        match += 1
    else:
        mismatch += 1
        if tyb_date > actual_date:
            future_leak += 1
            if len(examples) < 5:
                examples.append(f'  race={race_id} actual={actual_date} tyb={tyb_date} (TYB is AFTER race!)')
        else:
            if len(examples) < 5:
                examples.append(f'  race={race_id} actual={actual_date} tyb={tyb_date} (TYB before race)')

print(f'  Checked: {total_checked} races')
print(f'  Match (same day): {match} ({match/total_checked*100:.1f}%)')
print(f'  Mismatch: {mismatch}')
print(f'  FUTURE LEAK (TYB after race): {future_leak}')
for e in examples: print(e)

# === Audit 2: Check IDM source - is it from TYB or could it be SED? ===
print("\n=== Audit 2: IDM value comparison ===", flush=True)

# If IDM comes from SED (post-race), it would correlate perfectly with finish position
# Check: correlation between IDM and finish_position for the SAME race
rows = db.execute('''
    SELECT e.race_id, e.horse_number, e.idm, r.finish_position
    FROM entries e
    JOIN results r ON e.race_id = r.race_id AND e.horse_number = r.horse_number
    WHERE e.idm IS NOT NULL AND r.finish_position IS NOT NULL
    AND e.race_id LIKE '26%'
    LIMIT 10000
''').fetchall()

if rows:
    # If IDM is post-race, winner should always have highest IDM
    winner_has_top_idm = 0
    total_races_checked = 0
    race_idms = defaultdict(list)
    for rid, hn, idm, fp in rows:
        race_idms[rid].append((idm, fp))

    for rid, entries in race_idms.items():
        if len(entries) < 5: continue
        total_races_checked += 1
        max_idm_fp = min(entries, key=lambda x: -x[0])[1]  # fp of horse with highest IDM
        if max_idm_fp == 1:
            winner_has_top_idm += 1

    pct = winner_has_top_idm / total_races_checked * 100
    print(f'  2026 races checked: {total_races_checked}')
    print(f'  Winner has highest IDM: {winner_has_top_idm} ({pct:.1f}%)')
    print(f'  If post-race IDM: would be ~100%. If pre-race: should be ~25-35%')
    if pct > 60:
        print(f'  WARNING: {pct:.1f}% is suspiciously high - possible SED IDM leak!')
    else:
        print(f'  OK: {pct:.1f}% is consistent with pre-race prediction')

# Also check IDM correlation with finish position
from statistics import correlation
idm_list = [idm for _, _, idm, _ in rows if idm and idm > 0]
fp_list = [fp for _, _, idm, fp in rows if idm and idm > 0]
if len(idm_list) > 100:
    # Manual Pearson correlation
    n = len(idm_list)
    mean_idm = sum(idm_list)/n; mean_fp = sum(fp_list)/n
    cov = sum((a-mean_idm)*(b-mean_fp) for a,b in zip(idm_list, fp_list))/n
    std_idm = (sum((a-mean_idm)**2 for a in idm_list)/n)**0.5
    std_fp = (sum((b-mean_fp)**2 for b in fp_list)/n)**0.5
    corr = cov/(std_idm*std_fp) if std_idm>0 and std_fp>0 else 0
    print(f'  Correlation(IDM, finish_position): {corr:.4f}')
    print(f'  If post-race: would be ~-0.8 to -1.0. If pre-race: ~-0.2 to -0.4')

# === Now prepare for Audit 3: IDM time-shift test ===
print("\n=== Audit 3: Preparing IDM time-shift test ===", flush=True)

# Build map: (horse_id, race_date) -> IDM from TYB
# Then for each race, use IDM from 1-2 weeks earlier (different race)
# This tests: if IDM from the CURRENT race's TYB is leaked, shifting breaks it

# Collect all IDMs per horse with dates
horse_idm_history = defaultdict(list)  # horse_id -> [(race_date, idm)]
for row in db.execute('''
    SELECT e.race_id, e.horse_number, e.horse_id, e.idm, r.race_date
    FROM entries e
    JOIN races r ON e.race_id = r.race_id
    WHERE e.idm IS NOT NULL AND e.horse_id IS NOT NULL
    ORDER BY r.race_date
''').fetchall():
    horse_idm_history[row[2]].append((row[4], row[3]))  # (date, idm)

# For time-shift: use the PREVIOUS race's IDM instead of current
# Build shifted IDM map: (race_id, horse_number) -> previous_idm
shifted_idm = {}
for row in db.execute('''
    SELECT e.race_id, e.horse_number, e.horse_id, r.race_date
    FROM entries e
    JOIN races r ON e.race_id = r.race_id
    WHERE e.horse_id IS NOT NULL
''').fetchall():
    rid, hn, hid, rdate = row
    history = horse_idm_history.get(hid, [])
    # Find the most recent IDM BEFORE this race
    prev_idm = None
    for d, idm in reversed(history):
        if d < rdate:
            prev_idm = idm
            break
    if prev_idm is not None:
        shifted_idm[(rid, hn)] = prev_idm

print(f'  Shifted IDM available for {len(shifted_idm):,} entries')

db.close()

# === Audit 3: Full simulation with current vs shifted vs shuffled IDM ===
print("\n=== Audit 3: Running simulations ===", flush=True)

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,idm,total_index,rider_index,run_style FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es:
        entry_cache[rid] = {}
        for e in es: entry_cache[rid][e[0]] = {'hid':e[1],'jockey':e[2],'idm':e[3],'total':e[4],'rider':e[5],'run_style':e[6]}
result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight_diff FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'weight_diff':row[4]})
race_cond = {}
for row in db.execute('SELECT race_id,track_condition FROM races').fetchall(): race_cond[row[0]] = row[1]
trio_cache = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall(): trio_cache[rid][combo] = odds
win_odds_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds_cache[rid] = {int(r[0]):r[1] for r in oz}
TY = [2021,2022,2023,2024,2025,2026]; B = 10000
db.close()

def softmax(sc, scale):
    s=[(x-50)*scale for x in sc]; mx=max(s); e=[math.exp(x-mx) for x in s]; t=sum(e)
    return [x/t for x in e]
def mktp(odds, beta):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p_**beta for p_ in raw]; ps=sum(pw)
    return [p_/ps for p_ in pw]
def blendf(m, mk, alpha):
    bl=[math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p_/s for p_ in bl]
def harville_trio(probs, i, j, k):
    total = 0.0
    for perm in permutations([i, j, k]):
        a,b,c = perm; s=sum(probs)
        if s<=0: return 0
        p1=probs[a]/s; s2=s-probs[a]
        if s2<=0: return 0
        p2=probs[b]/s2; s3=s2-probs[b]
        if s3<=0: return 0
        total += p1*p2*probs[c]/s3
    return total

def build_train(ts, te):
    jc=defaultdict(lambda:{'r':0,'w':0}); hr=defaultdict(list); tp=defaultdict(lambda:defaultdict(list))
    for rid,rd,vc,sf,dt in races_raw:
        if rd<ts or rd>=te: continue
        track=race_cond.get(rid,'良')
        for res in result_cache.get(rid,[]):
            hn,fp,hid=res['hn'],res['fp'],res['hid']
            ent=entry_cache.get(rid,{}).get(hn,{})
            jn=ent.get('jockey','')
            if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'weight_diff':res.get('weight_diff')})
                if len(hr[hid])>30: hr[hid]=hr[hid][-30:]
                if track: tp[hid][track].append(fp)
    return jc,hr,tp

def score_m7(h, rid, vc, sf, dt, jc, hr, tp, idm_override=None):
    ent = entry_cache.get(rid,{}).get(h,{})
    if idm_override is not None:
        base = idm_override if idm_override > 0 else 50.0
    else:
        idm = ent.get('idm'); base = idm if idm and idm > 0 else 50.0
    rider = ent.get('rider'); rider_b = rider if rider and rider > 0 else 0
    hid = ent.get('hid',''); track = race_cond.get(rid,'良'); track_b = 0
    if hid and hid in tp and track in tp[hid]:
        r = tp[hid][track]
        if len(r) >= 3: track_b = (6-sum(r)/len(r))*1.5
    rs = ent.get('run_style','')
    rs_b = {'逃げ':1.0,'先行':0.5,'好位差し':0.3,'差し':0,'追込':-0.3,'自在':0.3,'後方':-0.5}.get(rs,0)
    wb = 0
    if hid and hid in hr:
        rc = hr[hid]; rw = [r for r in rc[-3:] if r.get('weight_diff') is not None]
        if rw:
            ld = rw[-1]['weight_diff']
            if abs(ld) > 10: wb = -1.5
            elif abs(ld) <= 4: wb = 0.5
    fit_b = 0
    if hid and hid in hr:
        rc = hr[hid]
        dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
        if len(dr) >= 2: fit_b += (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:]))*0.8
        sr = [r for r in rc if r['surface'] == sf]
        if len(sr) >= 2: fit_b += (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:]))*0.8
    return base + rider_b + track_b + rs_b + wb + fit_b

def run_simulation(idm_mode, alpha=0.50, pred_max=8):
    """idm_mode: 'current', 'shifted', 'shuffled', 'zero'"""
    beta_v=1.03; scale=0.15
    yearly = {ty:{'b':0,'r':0,'h':0,'c':0} for ty in TY}

    for ty in TY:
        jc,hr,tp = build_train(f'{ty-1}-01-01', f'{ty}-01-01')

        # For shuffle mode, collect all IDMs for this year and shuffle
        if idm_mode == 'shuffled':
            year_idms = []
            for rid,rd,vc,sf,dt in races_raw:
                if rd<f'{ty}-01-01' or rd>=f'{ty+1}-01-01': continue
                for hn, ent in entry_cache.get(rid, {}).items():
                    if ent.get('idm') and ent['idm'] > 0:
                        year_idms.append(ent['idm'])
            random.shuffle(year_idms)
            shuffle_idx = [0]  # mutable counter

        for rid,rd,vc,sf,dt in races_raw:
            if rd<f'{ty}-01-01' or rd>=f'{ty+1}-01-01': continue
            res_list=result_cache.get(rid,[])
            if len(res_list)<5: continue
            t3=[r['hn'] for r in res_list if r['fp']<=3]
            if len(t3)<3: continue
            om=win_odds_cache.get(rid)
            if not om: continue
            hl=sorted(om.keys())
            if len(hl)<5: continue
            early=[om[h] for h in hl]; trio=trio_cache.get(rid,{})

            scores = []
            for h in hl:
                if idm_mode == 'current':
                    s = score_m7(h, rid, vc, sf, dt, jc, hr, tp)
                elif idm_mode == 'shifted':
                    prev = shifted_idm.get((rid, h))
                    s = score_m7(h, rid, vc, sf, dt, jc, hr, tp, idm_override=prev)
                elif idm_mode == 'shuffled':
                    si = shuffle_idx[0] % len(year_idms) if year_idms else 0
                    s = score_m7(h, rid, vc, sf, dt, jc, hr, tp, idm_override=year_idms[si] if year_idms else 50)
                    shuffle_idx[0] += 1
                elif idm_mode == 'zero':
                    s = score_m7(h, rid, vc, sf, dt, jc, hr, tp, idm_override=50.0)
                scores.append(s)

            mp=softmax(scores,scale); mkp=mktp(early,beta_v); bp=blendf(mp,mkp,alpha)
            rk=sorted(range(len(hl)),key=lambda i:-bp[i])
            top=sorted([hl[rk[0]],hl[rk[1]],hl[rk[2]]])
            combo=f'{top[0]}-{top[1]}-{top[2]}'
            mo=trio.get(combo,0)
            if mo<=0 or mo>500: continue
            tp_b=harville_trio(bp,rk[0],rk[1],rk[2])
            pb=(1/tp_b)*0.75 if tp_b>0 else 9999
            if pb>pred_max: continue
            hit=frozenset(top)==frozenset(t3[:3])
            pay=B*mo if hit else 0
            yearly[ty]['b']+=B; yearly[ty]['c']+=1; yearly[ty]['r']+=pay
            if hit: yearly[ty]['h']+=1

    tb=sum(v['b'] for v in yearly.values())
    tr=sum(v['r'] for v in yearly.values())
    rr=tr/tb*100 if tb>0 else 0
    rc=sum(v['c'] for v in yearly.values())
    hits=sum(v['h'] for v in yearly.values())
    yr_rrs = [yearly[ty]['r']/yearly[ty]['b']*100 if yearly[ty]['b']>0 else 0 for ty in TY]
    return rr, rc, hits, yr_rrs

# Run all modes
print("\nRunning simulations (alpha=0.50, PredB<=8)...", flush=True)
results = {}
for mode in ['current', 'shifted', 'shuffled', 'zero']:
    rr, rc, hits, yr = run_simulation(mode, alpha=0.50, pred_max=8)
    results[mode] = (rr, rc, hits, yr)
    yr_str = ' '.join(f'{r:>5.1f}%' for r in yr)
    print(f'  {mode:>10}: RR={rr:.1f}% R={rc} hits={hits} | {yr_str}', flush=True)

# Also test with alpha=0.70
print("\nRunning simulations (alpha=0.70, PredB<=8)...", flush=True)
for mode in ['current', 'shifted']:
    rr, rc, hits, yr = run_simulation(mode, alpha=0.70, pred_max=8)
    yr_str = ' '.join(f'{r:>5.1f}%' for r in yr)
    print(f'  {mode:>10}: RR={rr:.1f}% R={rc} hits={hits} | {yr_str}', flush=True)

# Summary
print("\n=== IDM LEAK AUDIT SUMMARY ===", flush=True)
print(f'  TYB date match: {match}/{total_checked} ({match/total_checked*100:.1f}%)', flush=True)
print(f'  Future leak (TYB after race): {future_leak}', flush=True)
c = results['current'][0]; s = results['shifted'][0]; z = results['zero'][0]; sh = results['shuffled'][0]
print(f'  Current IDM:  {c:.1f}%', flush=True)
print(f'  Shifted IDM:  {s:.1f}% (diff: {s-c:+.1f}pt)', flush=True)
print(f'  Shuffled IDM: {sh:.1f}% (diff: {sh-c:+.1f}pt)', flush=True)
print(f'  Zero IDM:     {z:.1f}% (diff: {z-c:+.1f}pt)', flush=True)
if c - s > 15:
    print(f'  ALERT: Shifted drops {c-s:.1f}pt -> possible leak!', flush=True)
elif c - s > 5:
    print(f'  WARNING: Shifted drops {c-s:.1f}pt -> investigate further', flush=True)
else:
    print(f'  OK: Shifted only drops {c-s:.1f}pt -> IDM is likely pre-race', flush=True)
