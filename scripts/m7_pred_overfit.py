"""M7 + PredBlend filter overfitting check"""
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

beta_v=1.03; scale=0.15
ALPHAS = [0.30,0.40,0.45,0.50,0.55,0.60,0.70]
PRED_LIMITS = [4,5,6,7,8,10]
MKT_LIMITS = [7,10,15]

# Pre-compute all (alpha, year) -> list of (pred_blend, market_odds, hit, pay)
print("Pre-computing all combos...", flush=True)
cache = {}
for alpha in ALPHAS:
    for ty in TY:
        jc,hr,tp = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
        results = []
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
            if mo<=0: continue
            tp_b=harville_trio(bp,rk[0],rk[1],rk[2])
            pb=(1/tp_b)*0.75 if tp_b>0 else 9999
            hit=frozenset(top)==frozenset(t3[:3])
            pay=B*mo if hit else 0
            results.append((pb, mo, hit, pay))
        cache[(alpha,ty)] = results
    print(f"  alpha={alpha:.2f} done", flush=True)
db.close()

def calc_rr(alpha, years, pred_max, mkt_max):
    tb=0; tr=0; rc=0; hits=0
    for ty in years:
        for pb,mo,hit,pay in cache[(alpha,ty)]:
            if pb>pred_max: continue
            if mo>mkt_max: continue
            tb+=B; tr+=pay; rc+=1
            if hit: hits+=1
    return tr/tb*100 if tb>0 else 0, rc, hits

out = open(r'C:\Users\moribro2201\Desktop\m7_pred_overfit.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

# === Test 1: Full grid alpha x pred_limit x mkt_limit ===
p('='*130)
p('=== Alpha x PredBlend x MarketOdds grid (M7) ===')
p('='*130)
p()

for mkt in [9999] + MKT_LIMITS:
    ml = f'Mkt<={mkt}' if mkt<9999 else 'Mkt=ALL'
    p(f'--- {ml} ---')
    h = f'{"alpha":>6}'
    for pl in PRED_LIMITS + [9999]:
        ll = f'PB<={pl}' if pl<9999 else 'ALL'
        h += f'  {ll:>12}'
    p(h)
    p('-'*(8+14*(len(PRED_LIMITS)+1)))
    for alpha in ALPHAS:
        line = f'{alpha:>5.2f} '
        for pl in PRED_LIMITS + [9999]:
            rr,rc,_ = calc_rr(alpha, TY, pl, mkt)
            line += f'  {rr:>5.1f}%({rc:>4})'
        p(line)
    p()

# === Test 2: Leave-One-Year-Out for top candidates ===
p('='*130)
p('=== Leave-One-Year-Out Validation ===')
p('='*130)
p()

candidates = [
    ('PredB<=5, Mkt=ALL', 5, 9999),
    ('PredB<=7, Mkt=ALL', 7, 9999),
    ('PredB<=5, Mkt<=10', 5, 10),
    ('Mkt<=10 only', 9999, 10),
    ('PredB<=7, Mkt<=15', 7, 15),
    ('PredB<=10, Mkt<=15', 10, 15),
]

for label, pred_max, mkt_max in candidates:
    p(f'--- {label} ---')
    p(f'  {"Held":>4} {"BestA":>6} {"Train5y":>8} {"TestRR":>7} {"TestR":>5} | year-by-year')
    p(f'  {"-"*80}')
    held_rrs = []
    for hi in range(6):
        held = TY[hi]; train = [y for y in TY if y != held]
        best_rr=-1; best_a=0
        for alpha in ALPHAS:
            rr,_,_ = calc_rr(alpha, train, pred_max, mkt_max)
            if rr>best_rr: best_rr=rr; best_a=alpha
        test_rr, test_rc, _ = calc_rr(best_a, [held], pred_max, mkt_max)
        train_detail = ' '.join(f'{calc_rr(best_a,[y],pred_max,mkt_max)[0]:>5.1f}%' for y in train)
        p(f'  {held:>4} a={best_a:.2f}  {best_rr:>7.1f}% {test_rr:>6.1f}% {test_rc:>5} | {train_detail}')
        held_rrs.append(test_rr)
    avg = sum(held_rrs)/len(held_rrs)
    plus = sum(1 for r in held_rrs if r>=100)
    p(f'  Avg={avg:.1f}% Plus={plus}/6')
    p()

# === Test 3: Half-Period ===
p('='*130)
p('=== Half-Period Test ===')
p('='*130)
p()
p(f'  {"Filter":>25} {"Dir":>15} {"TrainRR":>8} {"TestRR":>8} | train detail -> test detail')
p(f'  {"-"*100}')

for label, pred_max, mkt_max in candidates:
    for train_idx, test_idx, direction in [([0,1,2],[3,4,5],'21-23->24-26'), ([3,4,5],[0,1,2],'24-26->21-23')]:
        train_y = [TY[i] for i in train_idx]; test_y = [TY[i] for i in test_idx]
        best_rr=-1; best_a=0
        for alpha in ALPHAS:
            rr,_,_ = calc_rr(alpha, train_y, pred_max, mkt_max)
            if rr>best_rr: best_rr=rr; best_a=alpha
        test_rr,_,_ = calc_rr(best_a, test_y, pred_max, mkt_max)
        train_d = ' '.join(f'{calc_rr(best_a,[y],pred_max,mkt_max)[0]:>5.1f}%' for y in train_y)
        test_d = ' '.join(f'{calc_rr(best_a,[y],pred_max,mkt_max)[0]:>5.1f}%' for y in test_y)
        p(f'  {label:>25} {direction:>15} {best_rr:>7.1f}% {test_rr:>7.1f}% | {train_d} -> {test_d}')

# === Test 4: Alpha robustness per filter ===
p()
p('='*130)
p('=== Alpha Robustness per filter ===')
p('='*130)
p()
p(f'  {"Filter":>25} {"Best":>6} {"Worst":>6} {">=110":>5} {">=115":>5} {">=120":>5}')
p(f'  {"-"*65}')
for label, pred_max, mkt_max in candidates:
    rrs = [calc_rr(a, TY, pred_max, mkt_max)[0] for a in ALPHAS]
    best = max(rrs); worst = min(rrs)
    a110 = sum(1 for r in rrs if r>=110); a115 = sum(1 for r in rrs if r>=115); a120 = sum(1 for r in rrs if r>=120)
    p(f'  {label:>25} {best:>5.1f}% {worst:>5.1f}% {a110:>3}/{len(ALPHAS)} {a115:>3}/{len(ALPHAS)} {a120:>3}/{len(ALPHAS)}')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\m7_pred_overfit.txt", flush=True)
