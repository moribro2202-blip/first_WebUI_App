"""
指摘5: Harville λ補正（Stern correction）
- 素のHarville（λ=1）は人気馬の2・3着確率を過大評価
- λ1=0.8, λ2=0.6 で補正して比較
- キャリブレーション（予測確率 vs 実測的中率）も計算（指摘6）
"""
import sqlite3, math, sys
from collections import defaultdict
from itertools import permutations
sys.stdout.reconfigure(encoding='utf-8')

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
print("Data loaded.", flush=True)

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

def harville_trio_lambda(probs, i, j, k, lam1=1.0, lam2=1.0):
    """Stern-corrected Harville: P(2nd) uses p^λ1, P(3rd) uses p^λ2"""
    total = 0.0
    for perm in permutations([i, j, k]):
        a, b, c = perm
        # 1st place: normal
        s = sum(probs)
        if s <= 0: return 0
        p1 = probs[a] / s
        # 2nd place: use λ1
        remaining = [p for idx, p in enumerate(probs) if idx != a]
        rem_lambda = [p ** lam1 for p in remaining]
        s2 = sum(rem_lambda)
        if s2 <= 0: return 0
        b_idx_in_remaining = [idx for idx, p_idx in enumerate(probs) if idx != a].index(b)
        p2 = rem_lambda[b_idx_in_remaining] / s2
        # 3rd place: use λ2
        remaining2_orig = [p for idx, p in enumerate(probs) if idx != a and idx != b]
        rem_lambda2 = [p ** lam2 for p in remaining2_orig]
        s3 = sum(rem_lambda2)
        if s3 <= 0: return 0
        c_idx_in_remaining2 = [idx for idx, p_idx in enumerate(probs) if idx != a and idx != b].index(c)
        p3 = rem_lambda2[c_idx_in_remaining2] / s3
        total += p1 * p2 * p3
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

def score_m7(h,rid,vc,sf,dt,jc,hr,tp):
    ent=entry_cache.get(rid,{}).get(h,{})
    idm=ent.get('idm'); base=idm if idm and idm>0 else 50.0
    rider=ent.get('rider'); rider_b=rider if rider and rider>0 else 0
    hid=ent.get('hid',''); track=race_cond.get(rid,'良'); track_b=0
    if hid and hid in tp and track in tp[hid]:
        r=tp[hid][track]
        if len(r)>=3: track_b=(6-sum(r)/len(r))*1.5
    rs=ent.get('run_style','')
    rs_b={'逃げ':1.0,'先行':0.5,'好位差し':0.3,'差し':0,'追込':-0.3,'自在':0.3,'後方':-0.5}.get(rs,0)
    wb=0
    if hid and hid in hr:
        rc=hr[hid]; rw=[r for r in rc[-3:] if r.get('weight_diff') is not None]
        if rw:
            ld=rw[-1]['weight_diff']
            if abs(ld)>10: wb=-1.5
            elif abs(ld)<=4: wb=0.5
    fit_b=0
    if hid and hid in hr:
        rc=hr[hid]
        dr=[r for r in rc if r['dist'] and abs(r['dist']-dt)<=200]
        if len(dr)>=2: fit_b+=(6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:]))*0.8
        sr=[r for r in rc if r['surface']==sf]
        if len(sr)>=2: fit_b+=(6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:]))*0.8
    return base+rider_b+track_b+rs_b+wb+fit_b

beta_v=1.03; scale=0.15; alpha=0.50

# Lambda configs to test
LAMBDA_CONFIGS = [
    ('Harville(1.0,1.0)', 1.0, 1.0),   # Standard (current)
    ('Stern(0.8,0.6)', 0.8, 0.6),       # Stern recommended
    ('Stern(0.9,0.8)', 0.9, 0.8),       # Mild correction
    ('Stern(0.7,0.5)', 0.7, 0.5),       # Strong correction
    ('Stern(0.85,0.7)', 0.85, 0.7),     # In-between
]

PRED_LIMITS = [5, 6, 7, 8, 10]

print("Running lambda comparison...", flush=True)

# Collect per-race results for all lambda configs
results_by_config = {}  # (lam_name, pred_max) -> {year: {b,r,h,c}}
calibration_data = {}   # lam_name -> list of (predicted_prob, actual_hit)

for lam_name, lam1, lam2 in LAMBDA_CONFIGS:
    cal_data = []
    for ty in TY:
        jc,hr,tp = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
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
            sc=[score_m7(h,rid,vc,sf,dt,jc,hr,tp) for h in hl]
            mp=softmax(sc,scale); mkp=mktp(early,beta_v); bp=blendf(mp,mkp,alpha)
            rk=sorted(range(len(hl)),key=lambda i:-bp[i])
            top=sorted([hl[rk[0]],hl[rk[1]],hl[rk[2]]])
            combo=f'{top[0]}-{top[1]}-{top[2]}'
            mo=trio.get(combo,0)
            if mo<=0 or mo>500: continue

            # Trio probability with lambda correction
            trio_prob = harville_trio_lambda(bp, rk[0], rk[1], rk[2], lam1, lam2)
            pb = (1/trio_prob)*0.75 if trio_prob > 0 else 9999

            hit = frozenset(top) == frozenset(t3[:3])
            pay = B*mo if hit else 0

            # Store for calibration
            cal_data.append((trio_prob, hit))

            # Store for each pred_max threshold
            for pm in PRED_LIMITS:
                key = (lam_name, pm)
                if key not in results_by_config:
                    results_by_config[key] = {y:{'b':0,'r':0,'h':0,'c':0} for y in TY}
                if pb <= pm:
                    results_by_config[key][ty]['b'] += B
                    results_by_config[key][ty]['c'] += 1
                    results_by_config[key][ty]['r'] += pay
                    if hit: results_by_config[key][ty]['h'] += 1

    calibration_data[lam_name] = cal_data
    print(f"  {lam_name} done", flush=True)

# === Output ===
out = open(r'C:\Users\moribro2201\Desktop\harville_lambda_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

p('='*130)
p('=== Harville Lambda Correction Comparison ===')
p('='*130)
p()

for pm in PRED_LIMITS:
    p(f'--- PredB <= {pm} ---')
    p(f'  {"Lambda Config":>22} {"RR":>7} {"R":>6} {"Hits":>5} {"HR":>6} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
    p(f'  {"-"*100}')
    for lam_name, _, _ in LAMBDA_CONFIGS:
        key = (lam_name, pm)
        d = results_by_config[key]
        tb = sum(v['b'] for v in d.values())
        tr = sum(v['r'] for v in d.values())
        rc = sum(v['c'] for v in d.values())
        hits = sum(v['h'] for v in d.values())
        rr = tr/tb*100 if tb>0 else 0
        hr = hits/rc*100 if rc>0 else 0
        yr = ' '.join(f'{d[ty]["r"]/d[ty]["b"]*100 if d[ty]["b"]>0 else 0:>6.1f}%' for ty in TY)
        p(f'  {lam_name:>22} {rr:>6.1f}% {rc:>6} {hits:>5} {hr:>5.1f}% | {yr}')
    p()

# === Calibration ===
p('='*130)
p('=== Calibration: Predicted Probability vs Actual Hit Rate ===')
p('='*130)
p()

prob_bins = [(0.00,0.05),(0.05,0.10),(0.10,0.15),(0.15,0.20),(0.20,0.25),(0.25,0.30),(0.30,0.40),(0.40,0.60)]

for lam_name, _, _ in LAMBDA_CONFIGS:
    p(f'--- {lam_name} ---')
    p(f'  {"Pred Prob":>12} {"Count":>7} {"Actual HR":>10} {"Pred Avg":>9} {"Ratio":>7}')
    p(f'  {"-"*55}')
    cal = calibration_data[lam_name]
    for lo, hi in prob_bins:
        subset = [(prob, hit) for prob, hit in cal if lo <= prob < hi]
        if not subset: continue
        n = len(subset)
        actual_hr = sum(1 for _, hit in subset if hit) / n
        avg_pred = sum(prob for prob, _ in subset) / n
        ratio = actual_hr / avg_pred if avg_pred > 0 else 0
        p(f'  {lo:.2f}-{hi:.2f}   {n:>7} {actual_hr:>9.3f} {avg_pred:>9.3f} {ratio:>6.2f}x')

    # Overall calibration
    all_pred = [prob for prob, _ in cal if prob > 0]
    all_hit = [1 if hit else 0 for _, hit in cal if True]
    avg_pred_all = sum(all_pred) / len(all_pred) if all_pred else 0
    avg_hit_all = sum(all_hit) / len(all_hit) if all_hit else 0
    p(f'  {"Overall":>12} {len(cal):>7} {avg_hit_all:>9.3f} {avg_pred_all:>9.3f} {avg_hit_all/avg_pred_all if avg_pred_all>0 else 0:>6.2f}x')
    p()

# === Summary ===
p('='*130)
p('=== Summary ===')
p('='*130)
p()
p(f'  {"Config":>22} {"PB<=5 RR":>9} {"PB<=8 RR":>9} {"PB<=5 R":>8} {"PB<=8 R":>8} {"Calib":>7}')
p(f'  {"-"*70}')
for lam_name, _, _ in LAMBDA_CONFIGS:
    rr5 = 0; rr8 = 0; r5 = 0; r8 = 0
    d5 = results_by_config.get((lam_name, 5))
    d8 = results_by_config.get((lam_name, 8))
    if d5:
        tb = sum(v['b'] for v in d5.values()); tr = sum(v['r'] for v in d5.values())
        rr5 = tr/tb*100 if tb>0 else 0; r5 = sum(v['c'] for v in d5.values())
    if d8:
        tb = sum(v['b'] for v in d8.values()); tr = sum(v['r'] for v in d8.values())
        rr8 = tr/tb*100 if tb>0 else 0; r8 = sum(v['c'] for v in d8.values())
    # Calibration ratio
    cal = calibration_data[lam_name]
    pred_avg = sum(prob for prob, _ in cal) / len(cal) if cal else 0
    hit_avg = sum(1 for _, hit in cal if hit) / len(cal) if cal else 0
    cal_ratio = hit_avg / pred_avg if pred_avg > 0 else 0
    p(f'  {lam_name:>22} {rr5:>8.1f}% {rr8:>8.1f}% {r5:>8} {r8:>8} {cal_ratio:>6.2f}x')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\harville_lambda_results.txt", flush=True)
