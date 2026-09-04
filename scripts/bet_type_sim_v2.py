"""M7全券種シミュレーション v2 - シンプル版"""
import sqlite3, math, sys
from collections import defaultdict
from itertools import permutations
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB_PATH)

TY = [2021,2022,2023,2024,2025,2026]; B = 10000

# Load data
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,idm,rider_index,run_style FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'idm':e[3],'rider':e[4],'run_style':e[5]} for e in es}
result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight_diff FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'wd':row[4]})
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
win_odds = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds[rid] = {int(r[0]):r[1] for r in oz}

print("Data loaded.", flush=True)

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

# Compute rankings
print("Computing rankings...", flush=True)
rankings = {}
for ty in TY:
    jc,hr,tp = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
    for rid,rd,vc,sf,dt in races_raw:
        if rd<f'{ty}-01-01' or rd>=f'{ty+1}-01-01': continue
        rl=result_cache.get(rid,[])
        if len(rl)<5: continue
        om=win_odds.get(rid)
        if not om: continue
        hl=sorted(om.keys())
        if len(hl)<5: continue
        sc=[score_m7(h,rid,vc,sf,dt,jc,hr,tp) for h in hl]
        mp=softmax(sc);mkp=mktp([om[h] for h in hl]);bp=blend(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        ranked=[hl[r] for r in rk]
        if len(rk)>=3:
            pb_val=h_stern(bp,rk[0],rk[1],rk[2])
            pb=(1/pb_val)*0.75 if pb_val>0 else 9999
        else: pb=9999
        t1=rl[0]['hn']; t2=rl[1]['hn'] if len(rl)>1 else None
        t3=set(r['hn'] for r in rl if r['fp']<=3)
        rankings[rid]={'date':rd,'year':ty,'ranked':ranked,'pb':pb,'t1':t1,'t2':t2,'t3':t3}

print(f"  {len(rankings)} races", flush=True)

# Simulate
def sim(filter_pb=None):
    strategies = []

    def run(label, bet_type_db, combo_fn, hit_fn):
        yrs={y:{'b':0,'r':0,'h':0} for y in TY}
        for rid,rd in rankings.items():
            if filter_pb and rd['pb']>filter_pb: continue
            combo=combo_fn(rd)
            if isinstance(combo,list):
                # Multi-point
                for c in combo:
                    o=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",(rid,bet_type_db,c)).fetchone()
                    if not o or o[0]<=0 or o[0]>500: continue
                    yrs[rd['year']]['b']+=B
                    if hit_fn(rd,c):
                        yrs[rd['year']]['r']+=int(B*o[0])
                        yrs[rd['year']]['h']+=1
            else:
                o=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",(rid,bet_type_db,combo)).fetchone()
                if not o or o[0]<=0 or o[0]>500: continue
                yrs[rd['year']]['b']+=B
                if hit_fn(rd,combo):
                    yrs[rd['year']]['r']+=int(B*o[0])
                    yrs[rd['year']]['h']+=1
        tb=sum(v['b'] for v in yrs.values()); tr=sum(v['r'] for v in yrs.values())
        hits=sum(v['h'] for v in yrs.values()); rc=tb//B
        rr=tr/tb*100 if tb>0 else 0; hr_=hits/rc*100 if rc>0 else 0
        yr=[yrs[y]['r']/yrs[y]['b']*100 if yrs[y]['b']>0 else 0 for y in TY]
        strategies.append((label,rr,rc,hits,hr_,yr))

    r_=lambda d:d['ranked']
    run('単勝 ◎','win', lambda d:str(r_(d)[0]), lambda d,c:d['t1']==r_(d)[0])
    run('複勝 ◎','place', lambda d:str(r_(d)[0]), lambda d,c:r_(d)[0] in d['t3'])
    run('複勝 ○','place', lambda d:str(r_(d)[1]), lambda d,c:r_(d)[1] in d['t3'])
    run('ワイド ◎○','wide', lambda d:'-'.join(str(x) for x in sorted(r_(d)[:2])), lambda d,c:r_(d)[0] in d['t3'] and r_(d)[1] in d['t3'])
    run('ワイド ◎▲','wide', lambda d:'-'.join(str(x) for x in sorted([r_(d)[0],r_(d)[2]])), lambda d,c:r_(d)[0] in d['t3'] and r_(d)[2] in d['t3'])
    run('馬連 ◎○','umaren', lambda d:'-'.join(str(x) for x in sorted(r_(d)[:2])), lambda d,c:d['t1'] in r_(d)[:2] and d['t2'] in r_(d)[:2])
    run('馬単 ◎→○','umatan', lambda d:f"{r_(d)[0]}-{r_(d)[1]}", lambda d,c:d['t1']==r_(d)[0] and d['t2']==r_(d)[1])
    run('三連複 ◎○▲','sanrenpuku', lambda d:'-'.join(str(x) for x in sorted(r_(d)[:3])), lambda d,c:set(r_(d)[:3])==d['t3'])
    run('三連単 ◎→○→▲','sanrentan', lambda d:f"{r_(d)[0]}-{r_(d)[1]}-{r_(d)[2]}", lambda d,c:d['t1']==r_(d)[0] and d['t2']==r_(d)[1] and r_(d)[2] in d['t3'] and len(d['t3'])==3)

    # Multi-point
    run('ワイド ◎流し3点','wide',
        lambda d:['-'.join(str(x) for x in sorted([r_(d)[0],r_(d)[i]])) for i in range(1,4)],
        lambda d,c: all(int(x) in d['t3'] for x in c.split('-')))
    run('馬連 ◎流し3点','umaren',
        lambda d:['-'.join(str(x) for x in sorted([r_(d)[0],r_(d)[i]])) for i in range(1,4)],
        lambda d,c: d['t1'] in [int(x) for x in c.split('-')] and d['t2'] in [int(x) for x in c.split('-')])
    run('三連複 BOX4点','sanrenpuku',
        lambda d:['-'.join(str(x) for x in sorted([r_(d)[i],r_(d)[j],r_(d)[k]])) for i in range(4) for j in range(i+1,4) for k in range(j+1,4)],
        lambda d,c: set(int(x) for x in c.split('-'))==d['t3'])

    return strategies

out = open(r'C:\Users\moribro2201\Desktop\bet_type_simulation.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

for fname,fpb in [('全レース',None),('PredBlend<=8',8),('PredBlend<=5',5)]:
    print(f"  Simulating {fname}...", flush=True)
    res=sim(fpb)
    res.sort(key=lambda x:-x[1])
    p(f'\n{"="*120}')
    p(f'=== {fname} ===')
    p(f'{"="*120}')
    p(f'  {"賭け方":>20} {"回収率":>7} {"R数":>7} {"的中":>5} {"的中率":>7} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
    p(f'  {"-"*105}')
    for label,rr,rc,hits,hr_,yr in res:
        yrs=' '.join(f'{r:>6.0f}%' for r in yr)
        mk=' <<<' if rr>=100 else ''
        p(f'  {label:>20} {rr:>6.1f}% {rc:>7} {hits:>5} {hr_:>6.1f}% | {yrs}{mk}')

db.close(); out.close()
print("Done!", flush=True)
