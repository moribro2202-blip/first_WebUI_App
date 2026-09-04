"""
PredBlend 5-10の間のスイートスポット探索
- PredBの帯域ごとの回収率を細かく分析
- 「PredB <= X」の累積と「PredB X-Y」の帯域を両方見る
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

# Collect all bets with PredBlend value
print("Computing all bets...", flush=True)
all_bets = []  # (alpha, year, pred_blend, market_odds, hit, payout)
for alpha in [0.40, 0.50, 0.60, 0.70]:
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
            if mo<=0 or mo>500: continue  # exclude 9999.8 anomaly
            tp_b=harville_trio(bp,rk[0],rk[1],rk[2])
            pb=(1/tp_b)*0.75 if tp_b>0 else 9999
            hit=frozenset(top)==frozenset(t3[:3])
            pay=B*mo if hit else 0
            all_bets.append((alpha, ty, pb, mo, hit, pay))
    print(f"  alpha={alpha} done", flush=True)
db.close()

out = open(r'C:\Users\moribro2201\Desktop\m7_sweetspot.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

# === 1. PredB band analysis (帯域ごとの回収率) ===
p('='*120)
p('=== 1. PredBlend Band Analysis: RR per band ===')
p('='*120)
p()

bands = [(0,2),(2,3),(3,4),(4,5),(5,6),(6,7),(7,8),(8,9),(9,10),(10,12),(12,15),(15,20),(20,30),(30,999)]

for alpha in [0.50, 0.70]:
    p(f'--- alpha={alpha} ---')
    p(f'  {"PredB Band":>12} {"R count":>7} {"Hits":>5} {"HitRate":>8} {"AvgMktO":>8} {"RR":>7} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
    p(f'  {"-"*110}')

    for lo, hi in bands:
        subset = [(a,y,pb,mo,hit,pay) for a,y,pb,mo,hit,pay in all_bets if a==alpha and lo<=pb<hi]
        if not subset: continue
        tb = len(subset) * B
        tr = sum(pay for _,_,_,_,_,pay in subset)
        hits = sum(1 for _,_,_,_,hit,_ in subset if hit)
        hr = hits/len(subset)*100
        avg_mo = sum(mo for _,_,_,mo,_,_ in subset)/len(subset)
        rr = tr/tb*100

        yr_rrs = []
        for ty in TY:
            ys = [(pb,mo,hit,pay) for a,y,pb,mo2,hit,pay in subset if y==ty]
            if ys:
                ytb = len(ys)*B; ytr = sum(pay for _,_,_,pay in ys)
                yr_rrs.append(f'{ytr/ytb*100:>6.1f}%')
            else:
                yr_rrs.append(f'   {"---":>4}')

        label = f'{lo}-{hi}' if hi < 999 else f'{lo}+'
        p(f'  {label:>12} {len(subset):>7} {hits:>5} {hr:>7.1f}% {avg_mo:>7.1f}x {rr:>6.1f}% | {" ".join(yr_rrs)}')
    p()

# === 2. Cumulative PredB <= X (fine-grained) ===
p('='*120)
p('=== 2. Cumulative: PredB <= X (fine steps) ===')
p('='*120)
p()

thresholds = [2,3,4,4.5,5,5.5,6,6.5,7,7.5,8,9,10,12,15,20]

for alpha in [0.50, 0.70]:
    p(f'--- alpha={alpha} ---')
    p(f'  {"PredB <=":>9} {"R":>6} {"Hits":>5} {"HitRate":>8} {"RR":>7} {"PnL/yr":>10} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
    p(f'  {"-"*105}')

    for thresh in thresholds:
        subset = [(a,y,pb,mo,hit,pay) for a,y,pb,mo,hit,pay in all_bets if a==alpha and pb<=thresh]
        if not subset: continue
        tb = len(subset) * B
        tr = sum(pay for _,_,_,_,_,pay in subset)
        hits = sum(1 for _,_,_,_,hit,_ in subset if hit)
        hr = hits/len(subset)*100
        rr = tr/tb*100
        pnl_yr = (tr-tb)/6

        yr_rrs = []
        for ty in TY:
            ys = [(pay) for a,y,pb,mo,hit,pay in subset if y==ty]
            ytb = len(ys)*B; ytr = sum(ys)
            yr_rrs.append(f'{ytr/ytb*100:>6.1f}%' if ytb>0 else f'   {"---":>4}')

        p(f'  PB<={thresh:<5} {len(subset):>6} {hits:>5} {hr:>7.1f}% {rr:>6.1f}% {pnl_yr:>+9,.0f} | {" ".join(yr_rrs)}')
    p()

# === 3. Marginal RR: what does adding PredB X->Y contribute? ===
p('='*120)
p('=== 3. Marginal Contribution: Adding PredB band X-Y to <=X ===')
p('='*120)
p()

for alpha in [0.50, 0.70]:
    p(f'--- alpha={alpha} ---')
    p(f'  {"Expand":>15} {"Added R":>7} {"Added RR":>9} {"New Total RR":>12} {"Change":>7}')
    p(f'  {"-"*60}')

    steps = [(0,5),(5,6),(6,7),(7,8),(8,10),(10,15)]
    cum_tb = 0; cum_tr = 0
    for lo, hi in steps:
        band = [(a,y,pb,mo,hit,pay) for a,y,pb,mo,hit,pay in all_bets if a==alpha and lo<=pb<hi]
        if not band: continue
        band_tb = len(band)*B
        band_tr = sum(pay for _,_,_,_,_,pay in band)
        band_rr = band_tr/band_tb*100

        prev_rr = cum_tr/cum_tb*100 if cum_tb>0 else 0
        cum_tb += band_tb; cum_tr += band_tr
        new_rr = cum_tr/cum_tb*100

        label = f'PB {lo}-{hi}'
        p(f'  {label:>15} {len(band):>7} {band_rr:>8.1f}% {new_rr:>11.1f}% {new_rr-prev_rr:>+6.1f}pt')
    p()

# === 4. Profit maximization: PnL per year for different thresholds ===
p('='*120)
p('=== 4. Annual PnL (yen) by threshold ===')
p('='*120)
p()

for alpha in [0.50, 0.70]:
    p(f'--- alpha={alpha} ---')
    p(f'  {"PredB <=":>9} {"Total PnL":>12} | {"2021":>10} {"2022":>10} {"2023":>10} {"2024":>10} {"2025":>10} {"2026":>10}')
    p(f'  {"-"*90}')

    for thresh in [4,5,6,7,8,10,15]:
        yr_pnl = {}
        for ty in TY:
            ys = [(pay) for a,y,pb,mo,hit,pay in all_bets if a==alpha and y==ty and pb<=thresh]
            yr_pnl[ty] = sum(ys) - len(ys)*B
        total_pnl = sum(yr_pnl.values())
        yr_str = ' '.join(f'{yr_pnl[ty]:>+10,}' for ty in TY)
        p(f'  PB<={thresh:<5} {total_pnl:>+11,} | {yr_str}')
    p()

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\m7_sweetspot.txt", flush=True)
