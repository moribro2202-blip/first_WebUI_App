"""
Fable指摘: オッズ帯フィルタではなくEV閾値フィルタに置き換え
EV = q_final(trio) × market_trio_odds >= θ
θのスキャンで回収率とR数のトレードオフ曲線を出す
"""
import sqlite3, math, sys
from collections import defaultdict
from itertools import permutations
sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,idm,rider_index,run_style FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'idm':e[3],'rider':e[4],'run_style':e[5]} for e in es}
result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight_diff FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'wd':row[4]})
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
trio_cache = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku' AND odds>0 AND odds<500").fetchall():
    trio_cache[rid][combo] = odds
win_odds_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds_cache[rid] = {int(r[0]):r[1] for r in oz}
TY=[2021,2022,2023,2024,2025,2026]

def softmax(sc):
    s=[(x-50)*0.15 for x in sc];mx=max(s);e=[math.exp(x-mx) for x in s];t=sum(e)
    return [x/t for x in e]
def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds];s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv];pw=[p**1.03 for p in raw];ps=sum(pw)
    return [p/ps for p in pw]
def blend(m,mk):
    bl=[math.exp(0.5*math.log(max(a,1e-10))+0.5*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl);return [p/s for p in bl]
def h_stern(probs,i,j,k):
    total=0
    for perm in permutations([i,j,k]):
        a,b,c=perm;s=sum(probs)
        if s<=0: return 0
        p1=probs[a]/s
        r2=[p**0.9 if idx!=a else 0 for idx,p in enumerate(probs)];s2=sum(r2)
        if s2<=0: return 0
        p2=r2[b]/s2
        r3=[p**0.8 if idx!=a and idx!=b else 0 for idx,p in enumerate(probs)];s3=sum(r3)
        if s3<=0: return 0
        total+=p1*p2*r3[c]/s3
    return total
def build_train(ts,te):
    jc=defaultdict(lambda:{'r':0,'w':0});hr=defaultdict(list);tp=defaultdict(lambda:defaultdict(list))
    for rid,rd,vc,sf,dt in races_raw:
        if rd<ts or rd>=te: continue
        track=race_cond.get(rid,'良')
        for res in result_cache.get(rid,[]):
            hn,fp,hid=res['hn'],res['fp'],res['hid']
            ent=entry_cache.get(rid,{}).get(hn,{})
            jn=ent.get('jockey','')
            if jn:jc[jn]['r']+=1;fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'wd':res.get('wd')})
                if len(hr[hid])>30: hr[hid]=hr[hid][-30:]
                if track: tp[hid][track].append(fp)
    return jc,hr,tp
def score_m7(h,rid,vc,sf,dt,jc,hr,tp):
    ent=entry_cache.get(rid,{}).get(h,{})
    idm=ent.get('idm');base=idm if idm and idm>0 else 50.0
    rider=ent.get('rider');rb=rider if rider and rider>0 else 0
    hid=ent.get('hid','');track=race_cond.get(rid,'良');tb2=0
    if hid and hid in tp and track in tp[hid]:
        r=tp[hid][track]
        if len(r)>=3: tb2=(6-sum(r)/len(r))*1.5
    rs=ent.get('run_style','')
    rsb={'逃げ':1.0,'先行':0.5,'好位差し':0.3,'差し':0,'追込':-0.3,'自在':0.3,'後方':-0.5}.get(rs,0)
    wb=0
    if hid and hid in hr:
        rc=hr[hid];rw=[r for r in rc[-3:] if r.get('wd') is not None]
        if rw:
            ld=rw[-1]['wd']
            if abs(ld)>10: wb=-1.5
            elif abs(ld)<=4: wb=0.5
    fb=0
    if hid and hid in hr:
        rc=hr[hid]
        dr=[r for r in rc if r['dist'] and abs(r['dist']-dt)<=200]
        if len(dr)>=2: fb+=(6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:]))*0.8
        sr=[r for r in rc if r['surface']==sf]
        if len(sr)>=2: fb+=(6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:]))*0.8
    return base+rb+tb2+rsb+wb+fb

print("Computing...", flush=True)
all_bets=[]
for ty in TY:
    jc,hr,tp=build_train(f'{ty-1}-01-01',f'{ty}-01-01')
    for rid,rd,vc,sf,dt in races_raw:
        if rd<f'{ty}-01-01' or rd>=f'{ty+1}-01-01': continue
        rl=result_cache.get(rid,[])
        if len(rl)<5: continue
        t3=set(r['hn'] for r in rl if r['fp']<=3)
        if len(t3)<3: continue
        om=win_odds_cache.get(rid)
        if not om: continue
        hl=sorted(om.keys())
        if len(hl)<5: continue
        sc=[score_m7(h,rid,vc,sf,dt,jc,hr,tp) for h in hl]
        mp=softmax(sc);mkp=mktp([om[h] for h in hl]);bp=blend(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        if len(rk)<3: continue
        trio_prob=h_stern(bp,rk[0],rk[1],rk[2])
        pb=(1/trio_prob)*0.75 if trio_prob>0 else 9999
        if pb>8: continue
        top=sorted([hl[rk[0]],hl[rk[1]],hl[rk[2]]])
        combo=f'{top[0]}-{top[1]}-{top[2]}'
        market_odds=trio_cache.get(rid,{}).get(combo,0)
        if market_odds<=0: continue
        hit=set(top)==t3
        ev=trio_prob*market_odds  # EV = model_prob × market_odds
        all_bets.append((rd,pb,market_odds,hit,ty,ev,trio_prob))
all_bets.sort(key=lambda x:x[0])

print(f"Total PB<=8: {len(all_bets)}R")

# EV distribution
evs=[b[5] for b in all_bets]
print(f"EV range: {min(evs):.3f} - {max(evs):.3f}")
print(f"EV mean: {sum(evs)/len(evs):.3f}")
print(f"EV median: {sorted(evs)[len(evs)//2]:.3f}")

# θ scan
print(f'\n{"="*110}')
print(f'=== EV閾値スキャン (EV = model_prob × market_odds >= θ) ===')
print(f'{"="*110}')
print(f'  {"θ":>5} {"R数":>5} {"的中":>4} {"的中率":>6} {"RR":>6} {"PnL/年":>9} {"Sharpe":>7} {"P年":>3} {"maxStrk":>7} | {"2021":>5} {"2022":>5} {"2023":>5} {"2024":>5} {"2025":>5} {"2026":>5}')
print(f'  {"-"*110}')

thetas=[0.5,0.6,0.7,0.75,0.8,0.85,0.9,0.95,1.0,1.05,1.1,1.15,1.2,1.25,1.3,1.4,1.5,1.6,1.8,2.0]

for theta in thetas:
    sub=[b for b in all_bets if b[5]>=theta]
    if len(sub)<50: continue
    rc=len(sub); hits=sum(1 for b in sub if b[3])
    tb=rc*10000; tr=sum(10000*b[2] for b in sub if b[3])
    rr=tr/tb*100
    returns=[(b[2]-1 if b[3] else -1) for b in sub]
    avg_ret=sum(returns)/len(returns)
    std=(sum((r-avg_ret)**2 for r in returns)/len(returns))**0.5
    sharpe=avg_ret/std if std>0 else 0
    streak=0;max_s=0
    for b in sub:
        if not b[3]: streak+=1;max_s=max(max_s,streak)
        else: streak=0
    yr_rrs=[]
    plus=0
    for y in TY:
        ys=[b for b in sub if b[4]==y]
        if ys:
            ytb=len(ys)*10000;ytr=sum(10000*b[2] for b in ys if b[3])
            yrr=ytr/ytb*100; yr_rrs.append(yrr)
            if yrr>=100: plus+=1
        else: yr_rrs.append(0)
    yr_str=' '.join(f'{r:>4.0f}%' for r in yr_rrs)
    pnl_yr=(tr-tb)/6/10000
    mk='<<<' if rr>=130 else ' <<' if rr>=120 else '  <' if rr>=110 else '   '
    print(f'  {theta:>5.2f} {rc:>5} {hits:>4} {hits/rc*100:>5.1f}% {rr:>5.1f}% {pnl_yr:>+8.0f}万 {sharpe:>7.3f} {plus:>3} {max_s:>7} | {yr_str} {mk}')

# Compare: EV filter vs odds band filter vs PB only
print(f'\n{"="*110}')
print(f'=== フィルタ方式の比較（同一パラメータ数の公平な比較）===')
print(f'{"="*110}')

comparisons=[
    ('PB<=8のみ(現行)',     lambda b: True, 0),
    ('PB<=8 + EV>=0.8',    lambda b: b[5]>=0.8, 1),
    ('PB<=8 + EV>=0.9',    lambda b: b[5]>=0.9, 1),
    ('PB<=8 + EV>=1.0',    lambda b: b[5]>=1.0, 1),
    ('PB<=8 + EV>=1.1',    lambda b: b[5]>=1.1, 1),
    ('PB<=8 + EV>=1.2',    lambda b: b[5]>=1.2, 1),
    ('PB<=8 + odds10-30',  lambda b: 10<=b[2]<30, 1),
    ('PB<=8 + odds5-25',   lambda b: 5<=b[2]<25, 1),
]
print(f'  {"フィルタ":>25} {"パラメータ数":>8} {"RR":>6} {"R数":>5} {"PnL/年":>9} {"Sharpe":>7} {"P年":>3} | {"年別RR"}')
print(f'  {"-"*100}')
for name,fn,params in comparisons:
    sub=[b for b in all_bets if fn(b)]
    if len(sub)<50: continue
    rc=len(sub);tb=rc*10000;tr=sum(10000*b[2] for b in sub if b[3])
    rr=tr/tb*100
    returns=[(b[2]-1 if b[3] else -1) for b in sub]
    avg_ret=sum(returns)/len(returns)
    std=(sum((r-avg_ret)**2 for r in returns)/len(returns))**0.5
    sharpe=avg_ret/std if std>0 else 0
    plus=0; yr_strs=[]
    for y in TY:
        ys=[b for b in sub if b[4]==y]
        if ys:
            yrr=sum(10000*b[2] for b in ys if b[3])/(len(ys)*10000)*100
            yr_strs.append(f'{yrr:>4.0f}%')
            if yrr>=100: plus+=1
        else: yr_strs.append('   -')
    pnl_yr=(tr-tb)/6/10000
    print(f'  {name:>25} {params:>8} {rr:>5.1f}% {rc:>5} {pnl_yr:>+8.0f}万 {sharpe:>7.3f} {plus:>3} | {" ".join(yr_strs)}')

# EV distribution by odds band (to verify Fable's hypothesis)
print(f'\n{"="*110}')
print(f'=== EV分布 × オッズ帯（Fable仮説の検証）===')
print(f'{"="*110}')
print(f'  {"オッズ帯":>10} {"R数":>5} {"平均EV":>7} {"中央EV":>7} {"EV>=1.0":>7} {"EV>=1.2":>7}')
print(f'  {"-"*50}')
for lo,hi in [(0,5),(5,10),(10,15),(15,20),(20,30),(30,50)]:
    sub=[b for b in all_bets if lo<=b[2]<hi]
    if not sub: continue
    evlist=[b[5] for b in sub]
    evlist.sort()
    avg_ev=sum(evlist)/len(evlist)
    med_ev=evlist[len(evlist)//2]
    ge10=sum(1 for e in evlist if e>=1.0)/len(evlist)*100
    ge12=sum(1 for e in evlist if e>=1.2)/len(evlist)*100
    print(f'  {lo:>3}-{hi:>3}倍 {len(sub):>5} {avg_ev:>7.3f} {med_ev:>7.3f} {ge10:>6.1f}% {ge12:>6.1f}%')

db.close()
