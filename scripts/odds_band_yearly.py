"""
M7 v25: オッズ帯別 x 年別の回収率
PB<=8フィルタ固定、三連複オッズ帯で分けて年ごとに検証
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
TY = [2021,2022,2023,2024,2025,2026]; B = 10000

def softmax(sc):
    s=[(x-50)*0.15 for x in sc]; mx=max(s); e=[math.exp(x-mx) for x in s]; t=sum(e)
    return [x/t for x in e]
def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p**1.03 for p in raw]; ps=sum(pw)
    return [p/ps for p in pw]
def blend(m,mk):
    bl=[math.exp(0.5*math.log(max(a,1e-10))+0.5*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p/s for p in bl]
def h_stern(probs,i,j,k):
    total=0
    for perm in permutations([i,j,k]):
        a,b,c=perm; s=sum(probs)
        if s<=0: return 0
        p1=probs[a]/s
        r2=[p**0.9 if idx!=a else 0 for idx,p in enumerate(probs)]; s2=sum(r2)
        if s2<=0: return 0
        p2=r2[b]/s2
        r3=[p**0.8 if idx!=a and idx!=b else 0 for idx,p in enumerate(probs)]; s3=sum(r3)
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
            if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'wd':res.get('wd')})
                if len(hr[hid])>30: hr[hid]=hr[hid][-30:]
                if track: tp[hid][track].append(fp)
    return jc,hr,tp
def score_m7(h,rid,vc,sf,dt,jc,hr,tp):
    ent=entry_cache.get(rid,{}).get(h,{})
    idm=ent.get('idm'); base=idm if idm and idm>0 else 50.0
    rider=ent.get('rider'); rb=rider if rider and rider>0 else 0
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
all_bets = []
for ty in TY:
    jc,hr,tp = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
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
        all_bets.append((pb, odds, hit, ty))

print(f"Total PB<=8 bets: {len(all_bets)}")

# Odds band strategies
strategies = {
    'A: 全オッズ (現行)':       lambda o: True,
    'B: 0-10倍のみ':           lambda o: o < 10,
    'C: 10-30倍のみ':          lambda o: 10 <= o < 30,
    'D: 0-15倍':               lambda o: o < 15,
    'E: 5-20倍':               lambda o: 5 <= o < 20,
    'F: 5-30倍':               lambda o: 5 <= o < 30,
    'G: 10-20倍':              lambda o: 10 <= o < 20,
    'H: 0-30倍':               lambda o: o < 30,
}

print(f'\n{"="*120}')
print(f'=== オッズ帯フィルタ x 年別回収率 (PB<=8) ===')
print(f'{"="*120}')

for sname, sfn in strategies.items():
    yearly = {y:{'b':0,'r':0,'h':0} for y in TY}
    for pb, odds, hit, year in all_bets:
        if not sfn(odds): continue
        yearly[year]['b'] += B
        if hit:
            yearly[year]['r'] += int(B * odds)
            yearly[year]['h'] += 1

    tb = sum(v['b'] for v in yearly.values())
    tr = sum(v['r'] for v in yearly.values())
    rc = tb // B
    hits = sum(v['h'] for v in yearly.values())
    if tb == 0: continue
    rr = tr/tb*100
    hr_ = hits/rc*100

    yr_str = ''
    plus_years = 0
    for y in TY:
        if yearly[y]['b'] > 0:
            yrr = yearly[y]['r']/yearly[y]['b']*100
            yr_str += f' {yrr:>6.0f}%'
            if yrr >= 100: plus_years += 1
        else:
            yr_str += f'      -'

    print(f'\n  {sname}')
    print(f'    Total: {rr:.1f}% ({rc}R {hits}hit {hr_:.1f}%) Plus={plus_years}/6年')
    print(f'    {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
    print(f'    {yr_str}')

# Best combo: PB x odds band
print(f'\n{"="*120}')
print(f'=== ベスト組み合わせ探索 ===')
print(f'{"="*120}')

best = []
for pb_max in [4, 5, 6, 7, 8]:
    for olo, ohi in [(0,10),(0,15),(0,20),(0,30),(5,15),(5,20),(5,30),(10,20),(10,30)]:
        yearly = {y:{'b':0,'r':0,'h':0} for y in TY}
        for pb, odds, hit, year in all_bets:
            if pb > pb_max: continue
            if not (olo <= odds < ohi): continue
            yearly[year]['b'] += B
            if hit:
                yearly[year]['r'] += int(B * odds)
                yearly[year]['h'] += 1
        tb = sum(v['b'] for v in yearly.values())
        if tb < 500 * B: continue  # minimum 500 races
        tr = sum(v['r'] for v in yearly.values())
        rc = tb // B; hits = sum(v['h'] for v in yearly.values())
        rr = tr/tb*100
        plus = sum(1 for y in TY if yearly[y]['b']>0 and yearly[y]['r']/yearly[y]['b']>=1.0)
        yr_rrs = [yearly[y]['r']/yearly[y]['b']*100 if yearly[y]['b']>0 else 0 for y in TY]
        best.append((rr, plus, rc, hits, pb_max, olo, ohi, yr_rrs))

best.sort(key=lambda x: (-x[1], -x[0]))
print(f'\n  {"PB":>3} {"Odds帯":>10} {"RR":>6} {"P年":>3} {"R数":>5} {"的中":>4} | {"2021":>6} {"2022":>6} {"2023":>6} {"2024":>6} {"2025":>6} {"2026":>6}')
print(f'  {"-"*85}')
for rr, plus, rc, hits, pb_max, olo, ohi, yr_rrs in best[:15]:
    yr_str = ' '.join(f'{r:>5.0f}%' for r in yr_rrs)
    print(f'  {pb_max:>3} {olo:>3}-{ohi:>3}倍 {rr:>5.1f}% {plus:>3} {rc:>5} {hits:>4} | {yr_str}')

db.close()
