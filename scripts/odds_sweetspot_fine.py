"""
三連複オッズ帯の細かいスイートスポット探索
同一投資額ベースで最も利益が出るオッズ帯を特定
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
        pb_val=h_stern(bp,rk[0],rk[1],rk[2])
        pb=(1/pb_val)*0.75 if pb_val>0 else 9999
        if pb>8: continue
        top=sorted([hl[rk[0]],hl[rk[1]],hl[rk[2]]])
        combo=f'{top[0]}-{top[1]}-{top[2]}'
        odds=trio_cache.get(rid,{}).get(combo,0)
        if odds<=0: continue
        hit=set(top)==t3
        all_bets.append((rd,pb,odds,hit,ty))
all_bets.sort(key=lambda x:x[0])

total_r = len(all_bets)
print(f"Total PB<=8: {total_r}R")

# 1. Fine-grained odds band analysis
print(f'\n{"="*90}')
print(f'=== 細かいオッズ帯別（2倍刻み）===')
print(f'{"="*90}')
print(f'  {"帯":>10} {"R数":>5} {"的中":>4} {"的中率":>6} {"RR":>6} {"同額換算PnL":>12} | 年別RR')
print(f'  {"-"*80}')

bands = [(0,3),(3,5),(5,7),(7,10),(10,12),(12,15),(15,18),(18,22),(22,28),(28,35),(35,50),(50,100)]
for lo,hi in bands:
    sub = [b for b in all_bets if lo<=b[2]<hi]
    if len(sub)<20: continue
    tb=len(sub)*10000; tr=sum(10000*o for _,_,o,h,_ in sub if h)
    hits=sum(1 for _,_,_,h,_ in sub if h)
    rr=tr/tb*100
    # Same investment as total: multiply bet by total_r/len(sub)
    mult=total_r/len(sub)
    adj_pnl=(tr-tb)*mult
    yr_rrs=[]
    for y in TY:
        ys=[b for b in sub if b[4]==y]
        if ys:
            ytb=len(ys)*10000; ytr=sum(10000*o for _,_,o,h,_ in ys if h)
            yr_rrs.append(f'{ytr/ytb*100:>5.0f}%')
        else:
            yr_rrs.append(f'    -')
    yr_str=' '.join(yr_rrs)
    mk='<<<' if rr>=120 else '  +' if rr>=100 else '   '
    print(f'  {lo:>3}-{hi:>3}倍 {len(sub):>5} {hits:>4} {hits/len(sub)*100:>5.1f}% {rr:>5.1f}% {adj_pnl/10000:>+10.0f}万 {mk} {yr_str}')

# 2. Sliding window: best contiguous odds range
print(f'\n{"="*90}')
print(f'=== スライディングウィンドウ（連続オッズ帯の最適幅）===')
print(f'{"="*90}')

results = []
for lo in range(0, 40, 2):
    for width in [5, 8, 10, 12, 15, 20, 25, 30]:
        hi = lo + width
        sub = [b for b in all_bets if lo<=b[2]<hi]
        if len(sub) < 300: continue
        tb=len(sub)*10000; tr=sum(10000*o for _,_,o,h,_ in sub if h)
        rr=tr/tb*100
        mult=total_r/len(sub)
        adj_pnl=(tr-tb)*mult/10000
        plus=sum(1 for y in TY if sum(1 for b in sub if b[4]==y)>0 and sum(10000*o for b in [x for x in sub if x[4]==y] if b[3])/(sum(1 for x in sub if x[4]==y)*10000)*100>=100)
        results.append((adj_pnl, rr, len(sub), lo, hi, plus))

results.sort(key=lambda x: -x[0])
print(f'\n  {"帯":>10} {"RR":>6} {"R数":>5} {"同額PnL":>10} {"P年":>3} | 年別RR')
print(f'  {"-"*70}')
seen = set()
for adj_pnl, rr, rc, lo, hi, plus in results[:20]:
    key = f'{lo}-{hi}'
    if key in seen: continue
    seen.add(key)
    yr_rrs=[]
    for y in TY:
        sub=[b for b in all_bets if lo<=b[2]<hi and b[4]==y]
        if sub:
            ytb=len(sub)*10000;ytr=sum(10000*o for _,_,o,h,_ in sub if h)
            yr_rrs.append(f'{ytr/ytb*100:>5.0f}%')
        else:
            yr_rrs.append(f'    -')
    yr_str=' '.join(yr_rrs)
    print(f'  {lo:>3}-{hi:>3}倍 {rr:>5.1f}% {rc:>5} {adj_pnl:>+9.0f}万 {plus:>3} | {yr_str}')

# 3. Compare best band vs current
print(f'\n{"="*90}')
print(f'=== ベスト帯 vs 現行 比較（同一投資額） ===')
print(f'{"="*90}')

comparisons = [
    ('現行(全オッズ)', lambda o: True),
    ('0-10倍', lambda o: o<10),
    ('5-15倍', lambda o: 5<=o<15),
    ('8-20倍', lambda o: 8<=o<20),
    ('10-22倍', lambda o: 10<=o<22),
    ('10-25倍', lambda o: 10<=o<25),
    ('10-30倍', lambda o: 10<=o<30),
    ('12-28倍', lambda o: 12<=o<28),
    ('8-25倍', lambda o: 8<=o<25),
    ('5-25倍', lambda o: 5<=o<25),
]

print(f'\n  {"戦略":>15} {"RR":>6} {"R数":>5} {"同額PnL(6年)":>13} {"年平均PnL":>10} {"P年":>3}')
print(f'  {"-"*60}')
for name, fn in comparisons:
    sub=[b for b in all_bets if fn(b[2])]
    if len(sub)<100: continue
    tb=len(sub)*10000; tr=sum(10000*o for _,_,o,h,_ in sub if h)
    rr=tr/tb*100
    mult=total_r/len(sub)
    adj_pnl=(tr-tb)*mult/10000
    plus=sum(1 for y in TY if sum(1 for x in sub if x[4]==y)>0 and sum(10000*o for x in [b for b in sub if b[4]==y] if x[3])/(sum(1 for x in sub if x[4]==y)*10000)*100>=100)
    print(f'  {name:>15} {rr:>5.1f}% {len(sub):>5} {adj_pnl:>+12.0f}万 {adj_pnl/6:>+9.0f}万 {plus:>3}')

db.close()
