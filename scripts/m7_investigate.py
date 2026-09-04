"""
1. PredB<=5のR数の十分性を検証
2. 2023年の異常値600%の原因調査
3. PredB<=5 vs 7 vs 10の安定性比較
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

# Collect all individual bets for detailed analysis
print("Computing all bets...", flush=True)
all_bets = []  # (alpha, year, month, rid, pred_blend, market_odds, hit, payout)
for alpha in [0.50, 0.60, 0.70]:
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
            if mo<=0: continue
            tp_b=harville_trio(bp,rk[0],rk[1],rk[2])
            pb=(1/tp_b)*0.75 if tp_b>0 else 9999
            hit=frozenset(top)==frozenset(t3[:3])
            pay=B*mo if hit else 0
            all_bets.append((alpha, ty, rd[:7], rid, pb, mo, hit, pay))
    print(f"  alpha={alpha} done", flush=True)
db.close()

out = open(r'C:\Users\moribro2201\Desktop\m7_investigate.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

# === 1. R数の年月別分布 (PredB<=5 vs 7 vs 10) ===
p('='*100)
p('=== 1. R数の年月別分布 ===')
p('='*100)
p()

for alpha in [0.50, 0.70]:
    for pred_max in [5, 7, 10]:
        p(f'--- alpha={alpha}, PredB<={pred_max} ---')
        h = f'{"":>8}'
        for ty in TY: h += f' {ty:>6}'
        h += f' {"Total":>6}'
        p(h)
        p('-'*55)
        months = [f'{m:02d}' for m in range(1,13)]
        yearly_total = {ty:0 for ty in TY}
        for m in months:
            line = f'  {m}    '
            m_total = 0
            for ty in TY:
                cnt = sum(1 for a,y,ym,_,pb,_,_,_ in all_bets if a==alpha and y==ty and ym==f'{ty}-{m}' and pb<=pred_max)
                yearly_total[ty] += cnt
                m_total += cnt
                line += f' {cnt:>6}'
            line += f' {m_total:>6}'
            p(line)
        line = f'  Total '
        grand = 0
        for ty in TY:
            line += f' {yearly_total[ty]:>6}'
            grand += yearly_total[ty]
        line += f' {grand:>6}'
        p(line)
        p(f'  Average per month: {grand/72:.1f}R')
        p()

# === 2. 2023年の異常値調査 (alpha=0.60, PredB<=10) ===
p('='*100)
p('=== 2. 2023年 alpha=0.60 PredB<=10 の異常値調査 ===')
p('='*100)
p()

# Find all hits in 2023 with alpha=0.60 and PredB<=10
hits_2023 = [(a,y,ym,rid,pb,mo,hit,pay) for a,y,ym,rid,pb,mo,hit,pay in all_bets
             if a==0.60 and y==2023 and pb<=10 and hit]
hits_2023.sort(key=lambda x: -x[7])  # sort by payout desc

p(f'2023年 alpha=0.60 PredB<=10: {len(hits_2023)} hits')
p()
p(f'  {"#":>3} {"Date":>8} {"RaceID":>10} {"PredB":>6} {"MktOdds":>8} {"Payout":>10}')
p(f'  {"-"*55}')
total_pay = sum(pay for _,_,_,_,_,_,_,pay in hits_2023)
for i, (a,y,ym,rid,pb,mo,hit,pay) in enumerate(hits_2023[:20]):
    p(f'  {i+1:>3} {ym:>8} {rid:>10} {pb:>5.1f}x {mo:>7.1f}x {pay:>+9,}')

p(f'\n  Total payout from hits: {total_pay:,}')
total_bet_cnt = sum(1 for a,y,ym,rid,pb,mo,hit,pay in all_bets if a==0.60 and y==2023 and pb<=10)
p(f'  Total bets: {total_bet_cnt}R ({total_bet_cnt*B:,} invested)')
p(f'  RR: {total_pay/(total_bet_cnt*B)*100:.1f}%')

# Find the big outlier
p(f'\n  Top 3 payouts:')
for i, (a,y,ym,rid,pb,mo,hit,pay) in enumerate(hits_2023[:3]):
    p(f'    #{i+1}: {rid} odds={mo:.1f}x payout={pay:,} ({pay/(total_bet_cnt*B)*100:.1f}% of total investment)')

# What happens without top outlier?
if hits_2023:
    top_pay = hits_2023[0][7]
    remaining = total_pay - top_pay
    rr_without = remaining / (total_bet_cnt * B) * 100
    p(f'\n  Without top 1 outlier: RR={rr_without:.1f}%')
    if len(hits_2023) > 1:
        top2_pay = hits_2023[0][7] + hits_2023[1][7]
        rr_without2 = (total_pay - top2_pay) / (total_bet_cnt * B) * 100
        p(f'  Without top 2 outliers: RR={rr_without2:.1f}%')

# Also check other years for comparison
p(f'\n  Comparison: Max single payout per year (alpha=0.60, PredB<=10)')
for ty in TY:
    hits_yr = [(pb,mo,pay) for a,y,_,_,pb,mo,hit,pay in all_bets if a==0.60 and y==ty and pb<=10 and hit]
    if hits_yr:
        max_pay = max(pay for _,_,pay in hits_yr)
        total_yr = sum(pay for _,_,pay in hits_yr)
        total_bets = sum(1 for a,y,_,_,pb,_,_,_ in all_bets if a==0.60 and y==ty and pb<=10)
        p(f'    {ty}: max={max_pay:>10,} total_pay={total_yr:>12,} bets={total_bets:>5} max_share={max_pay/total_yr*100:.1f}%')

# === 3. Outlier sensitivity for each PredB threshold ===
p()
p('='*100)
p('=== 3. Outlier Sensitivity: RR with/without top N payouts ===')
p('='*100)
p()

for alpha in [0.50, 0.70]:
    p(f'--- alpha={alpha} ---')
    p(f'  {"Filter":>10} {"Full RR":>8} {"w/o top1":>9} {"w/o top3":>9} {"w/o top5":>9} {"w/o top10":>10} {"MaxPay":>10} {"MaxShare":>9}')
    p(f'  {"-"*80}')
    for pred_max in [5, 7, 10, 15]:
        subset = [(pb,mo,hit,pay) for a,y,_,_,pb,mo,hit,pay in all_bets if a==alpha and pb<=pred_max]
        tb = len(subset) * B
        tr = sum(pay for _,_,_,pay in subset)
        full_rr = tr/tb*100 if tb>0 else 0

        hits = sorted([pay for _,_,hit,pay in subset if hit], reverse=True)
        if not hits: continue

        def rr_without_top_n(n):
            removed = sum(hits[:n])
            return (tr - removed) / tb * 100

        max_pay = hits[0]
        max_share = max_pay / tr * 100 if tr > 0 else 0

        p(f'  PredB<={pred_max:>2}   {full_rr:>7.1f}%  {rr_without_top_n(1):>7.1f}%  {rr_without_top_n(3):>7.1f}%  {rr_without_top_n(5):>7.1f}%   {rr_without_top_n(10):>7.1f}%  {max_pay:>9,}  {max_share:>7.1f}%')
    p()

# === 4. PredB<=5 statistical significance ===
p('='*100)
p('=== 4. Statistical Significance of PredB<=5 ===')
p('='*100)
p()

for alpha in [0.50, 0.70]:
    subset = [(pb,mo,hit,pay) for a,y,_,_,pb,mo,hit,pay in all_bets if a==alpha and pb<=5]
    n = len(subset)
    hits_n = sum(1 for _,_,hit,_ in subset if hit)
    hit_rate = hits_n / n
    tb = n * B
    tr = sum(pay for _,_,_,pay in subset)
    rr = tr / tb

    # Bootstrap-like: what's the std of returns?
    returns = [(pay - B) / B for _,_,_,pay in subset]
    avg_ret = sum(returns) / len(returns)
    var_ret = sum((r - avg_ret)**2 for r in returns) / len(returns)
    std_ret = var_ret ** 0.5
    se = std_ret / (n ** 0.5)
    t_stat = avg_ret / se if se > 0 else 0

    p(f'  alpha={alpha}, PredB<=5:')
    p(f'    N={n}, Hits={hits_n}, HitRate={hit_rate*100:.1f}%')
    p(f'    RR={rr*100:.1f}%, Avg return per bet={avg_ret*100:.1f}%')
    p(f'    Std per bet={std_ret*100:.1f}%, SE={se*100:.2f}%')
    p(f'    t-stat={t_stat:.2f} (>2.0 = significant at 95%)')
    p(f'    95% CI: [{(avg_ret-1.96*se)*100:.1f}%, {(avg_ret+1.96*se)*100:.1f}%]')
    p()

# === 5. Year-by-year R count and monthly minimum ===
p('='*100)
p('=== 5. Minimum monthly R count (PredB<=5 vs 7) ===')
p('='*100)
p()
for alpha in [0.50, 0.70]:
    for pred_max in [5, 7]:
        min_monthly = 999
        min_label = ''
        for ty in TY:
            for m in range(1,13):
                ym = f'{ty}-{m:02d}'
                cnt = sum(1 for a,y,ym2,_,pb,_,_,_ in all_bets if a==alpha and y==ty and ym2==ym and pb<=pred_max)
                if cnt > 0 and cnt < min_monthly:
                    min_monthly = cnt
                    min_label = ym
        total = sum(1 for a,_,_,_,pb,_,_,_ in all_bets if a==alpha and pb<=pred_max)
        avg_monthly = total / 72
        p(f'  alpha={alpha} PredB<={pred_max}: total={total}R avg/month={avg_monthly:.1f}R min={min_monthly}R ({min_label})')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\m7_investigate.txt", flush=True)
