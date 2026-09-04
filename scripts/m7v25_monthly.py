"""M7 v25 (Stern 0.9/0.8, PB<=8, alpha=0.50) monthly results"""
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
def harville_stern(probs, i, j, k, l1=0.9, l2=0.8):
    total = 0.0
    for perm in permutations([i,j,k]):
        a,b,c = perm; s=sum(probs)
        if s<=0: return 0
        p1=probs[a]/s
        rem2=[p**l1 if idx!=a else 0 for idx,p in enumerate(probs)]; s2=sum(rem2)
        if s2<=0: return 0
        p2=rem2[b]/s2
        rem3=[p**l2 if idx!=a and idx!=b else 0 for idx,p in enumerate(probs)]; s3=sum(rem3)
        if s3<=0: return 0
        p3=rem3[c]/s3
        total += p1*p2*p3
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

alpha=0.50; beta_v=1.03; scale=0.15; pred_max=8

monthly = {}
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
        tp_b=harville_stern(bp,rk[0],rk[1],rk[2])
        pb=(1/tp_b)*0.75 if tp_b>0 else 9999
        if pb>pred_max: continue
        hit=frozenset(top)==frozenset(t3[:3])
        pay=B*mo if hit else 0
        month=rd[5:7]
        key=(ty,month)
        if key not in monthly: monthly[key]={'b':0,'r':0,'h':0,'c':0}
        monthly[key]['b']+=B; monthly[key]['r']+=pay; monthly[key]['c']+=1
        if hit: monthly[key]['h']+=1

ms=['01','02','03','04','05','06','07','08','09','10','11','12']

# Year summary
print('=== Year Summary ===')
for ty in TY:
    tb=sum(monthly.get((ty,m),{'b':0})['b'] for m in ms)
    tr=sum(monthly.get((ty,m),{'r':0})['r'] for m in ms)
    hi=sum(monthly.get((ty,m),{'h':0})['h'] for m in ms)
    rc=sum(monthly.get((ty,m),{'c':0})['c'] for m in ms)
    if tb>0: print(f'{ty}: {rc}R {hi}hits {hi/rc*100:.1f}% RR={tr/tb*100:.1f}% PnL={tr-tb:+,.0f}')

tot_b=sum(monthly.get((ty,m),{'b':0})['b'] for ty in TY for m in ms)
tot_r=sum(monthly.get((ty,m),{'r':0})['r'] for ty in TY for m in ms)
tot_h=sum(monthly.get((ty,m),{'h':0})['h'] for ty in TY for m in ms)
tot_c=sum(monthly.get((ty,m),{'c':0})['c'] for ty in TY for m in ms)
print(f'Total: {tot_c}R {tot_h}hits {tot_h/tot_c*100:.1f}% RR={tot_r/tot_b*100:.1f}% PnL={tot_r-tot_b:+,.0f}')

# Monthly RR table
print('\n=== Monthly RR ===')
h='Month'
for ty in TY: h+=f'\t{ty}'
h+='\tAll'
print(h)
for m in ms:
    line=m
    mb=0;mr=0
    for ty in TY:
        d=monthly.get((ty,m),{'b':0,'r':0,'h':0,'c':0})
        if d['b']>0:
            rr=d['r']/d['b']*100; mb+=d['b']; mr+=d['r']
            line+=f'\t{rr:.0f}%({d["h"]}/{d["c"]})'
        else:
            line+=f'\t-'
    line+=f'\t{mr/mb*100:.1f}%' if mb>0 else '\t-'
    print(line)

# Cumulative PnL
print('\n=== Cumulative PnL ===')
h='Month'
for ty in TY: h+=f'\t{ty}'
h+='\tTotal'
print(h)
cum={ty:0 for ty in TY}; cum_total=0
for m in ms:
    line=m
    mp=0
    for ty in TY:
        d=monthly.get((ty,m),{'b':0,'r':0})
        pnl=d['r']-d['b']; cum[ty]+=pnl; mp+=pnl
        line+=f'\t{cum[ty]:+,}'
    cum_total+=mp
    line+=f'\t{cum_total:+,}'
    print(line)

# Monthly average
print('\n=== Monthly Average ===')
print('Month\tRR\tRaces\tHits\tHitRate\tAvgOdds')
for m in ms:
    tb=0;tr=0;hi=0;rc=0
    for ty in TY:
        d=monthly.get((ty,m),{'b':0,'r':0,'h':0,'c':0})
        tb+=d['b'];tr+=d['r'];hi+=d['h'];rc+=d['c']
    if tb>0:
        ao=tr/(hi*B) if hi>0 else 0
        print(f'{m}\t{tr/tb*100:.1f}%\t{rc}\t{hi}\t{hi/rc*100:.1f}%\t{ao:.1f}x')
