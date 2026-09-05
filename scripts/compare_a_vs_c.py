"""A(現行全オッズ) vs C(10-30倍) 同一投資額での比較"""
import sqlite3, math, sys
from collections import defaultdict
from itertools import permutations
sys.stdout.reconfigure(encoding='utf-8')

# Use precomputed data from odds_band_yearly
# Simpler approach: just load the bets already computed

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

print("Computing bets...", flush=True)
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
        all_bets.append((rd,rid,pb,odds,hit,ty))
all_bets.sort(key=lambda x:x[0])

a_bets=all_bets
c_bets=[b for b in all_bets if 10<=b[3]<30]

a_count=len(a_bets)
c_count=len(c_bets)
ratio=a_count/c_count

print(f"A: {a_count}R, C: {c_count}R, ratio: {ratio:.2f}")

# === Fixed amount: same per-race bet, compare total ===
print("\n" + "="*80)
print("=== 1. 同額ベット（1万円/R）: 総投資額が異なる ===")
print("="*80)

a_fixed=10000; c_fixed=10000
print(f"\n{'年':>5} | {'A投資':>10} {'A払戻':>10} {'A収支':>12} {'A RR':>6} | {'C投資':>10} {'C払戻':>10} {'C収支':>12} {'C RR':>6}")
print("-"*90)
for year in TY:
    ab=[b for b in a_bets if b[5]==year]
    cb=[b for b in c_bets if b[5]==year]
    ai=len(ab)*a_fixed; ar=sum(a_fixed*o for _,_,_,o,h,_ in ab if h)
    ci=len(cb)*c_fixed; cr=sum(c_fixed*o for _,_,_,o,h,_ in cb if h)
    print(f"{year:>5} | {ai:>9,}円 {ar:>9,}円 {ar-ai:>+11,}円 {ar/ai*100:>5.1f}% | {ci:>9,}円 {cr:>9,}円 {cr-ci:>+11,}円 {cr/ci*100 if ci>0 else 0:>5.1f}%")
ai=a_count*a_fixed; ar=sum(a_fixed*o for _,_,_,o,h,_ in a_bets if h)
ci=c_count*c_fixed; cr=sum(c_fixed*o for _,_,_,o,h,_ in c_bets if h)
print("-"*90)
print(f"{'合計':>5} | {ai:>9,}円 {ar:>9,}円 {ar-ai:>+11,}円 {ar/ai*100:>5.1f}% | {ci:>9,}円 {cr:>9,}円 {cr-ci:>+11,}円 {cr/ci*100:>5.1f}%")

# === Same total investment: C bets more per race ===
print("\n" + "="*80)
print(f"=== 2. 同一総投資額: Aは1万円/R、Cは{int(ratio*10000):,}円/R ===")
print("="*80)

c_adj=int(ratio*10000/100)*100
print(f"\n{'年':>5} | {'A投資':>10} {'A収支':>12} {'A RR':>6} | {'C投資':>10} {'C収支':>12} {'C RR':>6} | {'差':>10}")
print("-"*85)
for year in TY:
    ab=[b for b in a_bets if b[5]==year]
    cb=[b for b in c_bets if b[5]==year]
    ai=len(ab)*a_fixed; ar=sum(a_fixed*o for _,_,_,o,h,_ in ab if h)
    ci=len(cb)*c_adj; cr=sum(c_adj*o for _,_,_,o,h,_ in cb if h)
    a_pnl=ar-ai; c_pnl=cr-ci
    print(f"{year:>5} | {ai:>9,}円 {a_pnl:>+11,}円 {ar/ai*100:>5.1f}% | {ci:>9,}円 {c_pnl:>+11,}円 {cr/ci*100 if ci>0 else 0:>5.1f}% | {c_pnl-a_pnl:>+9,}円")

ai=a_count*a_fixed; ar=sum(a_fixed*o for _,_,_,o,h,_ in a_bets if h)
ci=c_count*c_adj; cr=sum(c_adj*o for _,_,_,o,h,_ in c_bets if h)
print("-"*85)
print(f"{'合計':>5} | {ai:>9,}円 {ar-ai:>+11,}円 {ar/ai*100:>5.1f}% | {ci:>9,}円 {cr-ci:>+11,}円 {cr/ci*100:>5.1f}% | {(cr-ci)-(ar-ai):>+9,}円")

# === Step-up from 200k ===
print("\n" + "="*80)
print("=== 3. 段階ベットアップ（初期20万、MAX2万） ===")
print("="*80)

step_table=[(0,2000),(200000,3000),(350000,5000),(600000,7000),(1000000,10000),(1500000,15000),(2500000,20000)]
def get_step(bal):
    bet=2000
    for mb,amt in step_table:
        if bal>=mb: bet=amt
    return min(bet,bal)

for label,bets,mult in [("A: 全オッズ",a_bets,1.0),("C: 10-30倍",c_bets,ratio)]:
    bal=200000
    yearly={y:{'start':0,'end':0} for y in TY}
    cur_year=None
    for rd,rid,pb,odds,hit,ty in bets:
        if ty!=cur_year:
            if cur_year: yearly[cur_year]['end']=bal
            cur_year=ty; yearly[ty]['start']=bal
        base=get_step(bal)
        bet=int(base*mult/100)*100
        bet=min(bet,bal)
        if bet<=0: break
        bal-=bet
        if hit: bal+=int(bet*odds)
    if cur_year: yearly[cur_year]['end']=bal

    print(f"\n  {label} (x{mult:.2f})")
    print(f"  {'年':>5} {'年初':>12} {'年末':>12} {'損益':>12}")
    print(f"  {'-'*45}")
    for y in TY:
        s=yearly[y]
        if s['start']>0 or s['end']>0:
            print(f"  {y:>5} {s['start']:>11,}円 {s['end']:>11,}円 {s['end']-s['start']:>+11,}円")
    print(f"  最終残高: {bal:,}円 (利益: {bal-200000:+,}円)")

db.close()
