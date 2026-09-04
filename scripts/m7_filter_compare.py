"""M7モデルで市場オッズ vs 予想オッズフィルタを比較"""
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
        for e in es:
            entry_cache[rid][e[0]] = {'hid':e[1],'jockey':e[2],'idm':e[3],'total':e[4],'rider':e[5],'run_style':e[6]}

result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight,horse_weight_diff FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'weight_diff':row[5]})

race_cond = {}
for row in db.execute('SELECT race_id,track_condition FROM races').fetchall():
    race_cond[row[0]] = row[1]

trio_cache = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    trio_cache[rid][combo] = odds

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
        a, b, c = perm
        s = sum(probs)
        if s <= 0: return 0
        p1 = probs[a]/s; s2 = s-probs[a]
        if s2 <= 0: return 0
        p2 = probs[b]/s2; s3 = s2-probs[b]
        if s3 <= 0: return 0
        p3 = probs[c]/s3
        total += p1*p2*p3
    return total

def build_train(ts, te):
    jc=defaultdict(lambda:{'r':0,'w':0}); hr=defaultdict(list)
    tp=defaultdict(lambda:defaultdict(list))
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
    hid=ent.get('hid','')
    track=race_cond.get(rid,'良'); track_b=0
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

alpha=0.50; beta_v=1.03; scale=0.15

# Compute per-race metrics
print("Computing race metrics...", flush=True)
race_metrics = []  # (year, hit, pay, market_odds, pred_odds_blend, pred_odds_mkt, ev)

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
        market_odds=trio.get(combo,0)
        if market_odds<=0: continue
        hit=frozenset(top)==frozenset(t3[:3])
        pay=B*market_odds if hit else 0

        # Predicted odds from blended probs (Harville)
        tp_blend = harville_trio(bp, rk[0], rk[1], rk[2])
        pred_blend = (1/tp_blend)*0.75 if tp_blend>0 else 9999

        # Predicted odds from market probs (Harville)
        tp_mkt = harville_trio(mkp, rk[0], rk[1], rk[2])
        pred_mkt = (1/tp_mkt)*0.75 if tp_mkt>0 else 9999

        # EV
        ev = tp_blend * market_odds if tp_blend>0 else 0

        race_metrics.append((ty, hit, pay, market_odds, pred_blend, pred_mkt, ev))

print(f"  {len(race_metrics)} race-bets computed", flush=True)
db.close()

out = open(r'C:\Users\moribro2201\Desktop\m7_filter_compare.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

def test_filter(metrics, fn):
    yearly = {}
    for ty, hit, pay, mo, pb, pm, ev in metrics:
        if not fn(mo, pb, pm, ev): continue
        if ty not in yearly: yearly[ty]={'b':0,'r':0,'h':0,'c':0}
        yearly[ty]['b']+=B; yearly[ty]['r']+=pay; yearly[ty]['c']+=1
        if hit: yearly[ty]['h']+=1
    tb=sum(v['b'] for v in yearly.values())
    tr=sum(v['r'] for v in yearly.values())
    rc=sum(v['c'] for v in yearly.values())
    rr=tr/tb*100 if tb>0 else 0
    parts=[]
    for ty in TY:
        if ty in yearly and yearly[ty]['b']>0:
            yrr=yearly[ty]['r']/yearly[ty]['b']*100
            parts.append(f'{yrr:>5.1f}%({yearly[ty]["c"]:>3}R)')
        else:
            parts.append(f'  {"---":>9}')
    return rr, rc, parts

p('='*130)
p('=== M7 Model: Market Odds vs Predicted Odds Filter Comparison ===')
p('='*130)
p()
p(f'  {"Filter":>35} {"TotalRR":>7} {"R":>5} | {"2021":>11} {"2022":>11} {"2023":>11} {"2024":>11} {"2025":>11} {"2026":>11}')
p(f'  {"-"*120}')

filters = [
    ('Market<=5',       lambda mo,pb,pm,ev: mo<=5),
    ('Market<=7',       lambda mo,pb,pm,ev: mo<=7),
    ('Market<=10',      lambda mo,pb,pm,ev: mo<=10),
    ('Market<=15',      lambda mo,pb,pm,ev: mo<=15),
    ('Market<=20',      lambda mo,pb,pm,ev: mo<=20),
    ('', None),
    ('PredBlend<=5',    lambda mo,pb,pm,ev: pb<=5),
    ('PredBlend<=7',    lambda mo,pb,pm,ev: pb<=7),
    ('PredBlend<=10',   lambda mo,pb,pm,ev: pb<=10),
    ('PredBlend<=15',   lambda mo,pb,pm,ev: pb<=15),
    ('', None),
    ('PredMkt<=5',      lambda mo,pb,pm,ev: pm<=5),
    ('PredMkt<=7',      lambda mo,pb,pm,ev: pm<=7),
    ('PredMkt<=10',     lambda mo,pb,pm,ev: pm<=10),
    ('PredMkt<=15',     lambda mo,pb,pm,ev: pm<=15),
    ('', None),
    ('Mkt<=10 & PredB<=7',   lambda mo,pb,pm,ev: mo<=10 and pb<=7),
    ('Mkt<=10 & PredB<=10',  lambda mo,pb,pm,ev: mo<=10 and pb<=10),
    ('Mkt<=10 & PredM<=7',   lambda mo,pb,pm,ev: mo<=10 and pm<=7),
    ('Mkt<=10 & PredM<=10',  lambda mo,pb,pm,ev: mo<=10 and pm<=10),
    ('Mkt<=15 & PredM<=10',  lambda mo,pb,pm,ev: mo<=15 and pm<=10),
    ('Mkt<=15 & PredB<=10',  lambda mo,pb,pm,ev: mo<=15 and pb<=10),
    ('', None),
    ('Mkt<=10 & EV>=1.0',    lambda mo,pb,pm,ev: mo<=10 and ev>=1.0),
    ('Mkt<=10 & EV>=1.05',   lambda mo,pb,pm,ev: mo<=10 and ev>=1.05),
    ('Mkt<=10 & EV>=1.10',   lambda mo,pb,pm,ev: mo<=10 and ev>=1.10),
    ('Mkt<=10 & EV>=0.90',   lambda mo,pb,pm,ev: mo<=10 and ev>=0.90),
    ('', None),
    ('PredM<=7 only',   lambda mo,pb,pm,ev: pm<=7),
    ('PredM<=7 & Mkt<=15',   lambda mo,pb,pm,ev: pm<=7 and mo<=15),
    ('PredM<=5 & Mkt<=10',   lambda mo,pb,pm,ev: pm<=5 and mo<=10),
    ('PredM<=5 & Mkt<=15',   lambda mo,pb,pm,ev: pm<=5 and mo<=15),
    ('', None),
    ('ALL (no filter)',  lambda mo,pb,pm,ev: True),
]

for label, fn in filters:
    if fn is None:
        p()
        continue
    rr, rc, parts = test_filter(race_metrics, fn)
    p(f'  {label:>35} {rr:>6.1f}% {rc:>5} | {" ".join(parts)}')

# Diagnostic: pred_odds distribution for M7 model
p()
p('='*80)
p('=== Diagnostic: M7 Predicted Odds vs Market Odds ===')
p('='*80)
p()
mkt_buckets = [(0,3),(3,5),(5,7),(7,10),(10,15),(15,20),(20,30),(30,9999)]
p(f'  {"Mkt Odds":>12} {"Count":>6} {"AvgPredB":>9} {"AvgPredM":>9} {"AvgEV":>7} {"HitRate":>7} {"RR":>6}')
p(f'  {"-"*65}')
for lo,hi in mkt_buckets:
    sub = [(ty,hit,pay,mo,pb,pm,ev) for ty,hit,pay,mo,pb,pm,ev in race_metrics if lo<mo<=hi]
    if not sub: continue
    apb = sum(pb for _,_,_,_,pb,_,_ in sub)/len(sub)
    apm = sum(pm for _,_,_,_,_,pm,_ in sub)/len(sub)
    aev = sum(ev for _,_,_,_,_,_,ev in sub)/len(sub)
    hits = sum(1 for _,hit,_,_,_,_,_ in sub if hit)
    hr = hits/len(sub)*100
    tb = len(sub)*B; tr = sum(pay for _,_,pay,_,_,_,_ in sub)
    rr = tr/tb*100
    label = f'{lo}-{hi}' if hi<9999 else f'{lo}+'
    p(f'  {label:>12} {len(sub):>6} {apb:>9.1f} {apm:>9.1f} {aev:>7.3f} {hr:>6.1f}% {rr:>5.1f}%')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\m7_filter_compare.txt", flush=True)
