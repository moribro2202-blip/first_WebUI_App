"""
総合最適戦略の探索
回収率 × R数 × 安定性 × 分散を総合評価
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
total_r=len(all_bets)

def evaluate(name, filter_fn):
    sub=[b for b in all_bets if filter_fn(b)]
    if len(sub)<100: return None
    rc=len(sub)
    hits=sum(1 for b in sub if b[3])
    tb=rc*10000; tr=sum(10000*b[2] for b in sub if b[3])
    rr=tr/tb*100
    # Per-bet returns for variance calc
    returns=[(b[2]-1 if b[3] else -1) for b in sub]
    avg_ret=sum(returns)/len(returns)
    var=sum((r-avg_ret)**2 for r in returns)/len(returns)
    std=var**0.5
    sharpe=avg_ret/std if std>0 else 0
    # Yearly
    yr_rrs=[]
    plus=0
    for y in TY:
        ys=[b for b in sub if b[4]==y]
        if ys:
            ytb=len(ys)*10000; ytr=sum(10000*b[2] for b in ys if b[3])
            yrr=ytr/ytb*100
            yr_rrs.append(yrr)
            if yrr>=100: plus+=1
        else:
            yr_rrs.append(0)
    yr_std=(sum((r-rr)**2 for r in yr_rrs if r>0)/max(1,sum(1 for r in yr_rrs if r>0)))**0.5
    # Same-investment PnL
    mult=total_r/rc
    adj_pnl=(tr-tb)*mult/10000
    # Max consecutive losses
    streak=0; max_streak=0
    for b in sub:
        if not b[3]: streak+=1; max_streak=max(max_streak,streak)
        else: streak=0
    return {
        'name':name,'rc':rc,'hits':hits,'rr':rr,'adj_pnl':adj_pnl,
        'std':std,'sharpe':sharpe,'plus':plus,'yr_rrs':yr_rrs,'yr_std':yr_std,
        'max_streak':max_streak,'mult':mult
    }

strategies=[
    ('A: 全オッズ(現行)',     lambda b: True),
    ('B: 0-10倍',           lambda b: b[2]<10),
    ('C: 10-30倍',          lambda b: 10<=b[2]<30),
    ('D: 5-20倍',           lambda b: 5<=b[2]<20),
    ('E: 5-25倍',           lambda b: 5<=b[2]<25),
    ('F: 8-22倍',           lambda b: 8<=b[2]<22),
    ('G: 10-20倍',          lambda b: 10<=b[2]<20),
    ('H: 12-15倍',          lambda b: 12<=b[2]<15),
    ('I: 7-18倍',           lambda b: 7<=b[2]<18),
    ('J: 5-15倍',           lambda b: 5<=b[2]<15),
    ('K: 0-20倍',           lambda b: b[2]<20),
    ('L: 3-15倍',           lambda b: 3<=b[2]<15),
    ('M: 全+12-15倍2倍賭',  None),  # special
]

results=[]
for name,fn in strategies:
    if fn is None: continue
    r=evaluate(name,fn)
    if r: results.append(r)

# Print comprehensive comparison
print(f'\n{"="*130}')
print(f'=== 総合評価 ===')
print(f'{"="*130}')
print(f'  {"戦略":>20} {"RR":>6} {"R数":>5} {"同額PnL":>9} {"的中率":>6} {"Sharpe":>7} {"年RRσ":>6} {"P年":>3} {"最大連敗":>6} {"倍率":>4} | {"2021":>5} {"2022":>5} {"2023":>5} {"2024":>5} {"2025":>5} {"2026":>5}')
print(f'  {"-"*125}')

results.sort(key=lambda x: -x['adj_pnl'])
for r in results:
    yr_str=' '.join(f'{rr:>4.0f}%' for rr in r['yr_rrs'])
    print(f'  {r["name"]:>20} {r["rr"]:>5.1f}% {r["rc"]:>5} {r["adj_pnl"]:>+8.0f}万 {r["hits"]/r["rc"]*100:>5.1f}% {r["sharpe"]:>7.3f} {r["yr_std"]:>5.1f} {r["plus"]:>3} {r["max_streak"]:>6} {r["mult"]:>4.1f} | {yr_str}')

# Recommendation
print(f'\n{"="*130}')
print(f'=== 推奨戦略 ===')
print(f'{"="*130}')

# Score each strategy: weighted combination
for r in results:
    # Normalize metrics
    r['score'] = (
        r['adj_pnl'] / 300 * 30 +          # PnL weight 30%
        r['rr'] / 150 * 20 +               # RR weight 20%
        r['sharpe'] * 100 * 15 +            # Sharpe weight 15%
        r['plus'] / 6 * 20 +               # Stability weight 20%
        (1 - r['yr_std']/50) * 15 +         # Low variance weight 15%
        0
    )

results.sort(key=lambda x: -x['score'])
print(f'\n  {"#":>2} {"戦略":>20} {"総合スコア":>8} {"PnL":>8} {"RR":>6} {"Sharpe":>7} {"P年":>3} {"年σ":>5}')
print(f'  {"-"*65}')
for i,r in enumerate(results[:5]):
    print(f'  {i+1:>2} {r["name"]:>20} {r["score"]:>8.1f} {r["adj_pnl"]:>+7.0f}万 {r["rr"]:>5.1f}% {r["sharpe"]:>7.3f} {r["plus"]:>3} {r["yr_std"]:>5.1f}')

# Hybrid strategy analysis
print(f'\n{"="*130}')
print(f'=== ハイブリッド戦略（全レース1万 + 12-15倍帯に追加1万）===')
print(f'{"="*130}')

hybrid_yearly = {y:{'b':0,'r':0} for y in TY}
for b in all_bets:
    rd,pb,odds,hit,ty = b
    # Base bet: 10000
    hybrid_yearly[ty]['b'] += 10000
    if hit: hybrid_yearly[ty]['r'] += int(10000*odds)
    # Extra bet on 12-15x
    if 12 <= odds < 15:
        hybrid_yearly[ty]['b'] += 10000
        if hit: hybrid_yearly[ty]['r'] += int(10000*odds)

print(f'  {"年":>5} {"投資":>12} {"払戻":>12} {"収支":>12} {"RR":>6}')
print(f'  {"-"*50}')
htb=0; htr=0
for y in TY:
    s=hybrid_yearly[y]
    htb+=s['b']; htr+=s['r']
    rr=s['r']/s['b']*100 if s['b']>0 else 0
    print(f'  {y:>5} {s["b"]:>11,}円 {s["r"]:>11,}円 {s["r"]-s["b"]:>+11,}円 {rr:>5.1f}%')
print(f'  {"合計":>5} {htb:>11,}円 {htr:>11,}円 {htr-htb:>+11,}円 {htr/htb*100:>5.1f}%')

db.close()
