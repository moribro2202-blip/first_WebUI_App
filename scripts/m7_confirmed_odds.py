"""
M7 + PredBlendフィルタで、払戻を確定オッズ(SED)ベースで計算
- フィルタ判断: PredBlend (モデル予想) → リーク無し
- 払戻計算: OT三連複オッズ(前日/確定混在) vs SED確定単勝オッズから推定
- 比較: 前日オッズ払戻 vs 確定オッズ補正払戻
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
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight_diff,win_odds FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'weight_diff':row[4],'confirmed_odds':row[5]})

race_cond = {}
for row in db.execute('SELECT race_id,track_condition FROM races').fetchall(): race_cond[row[0]] = row[1]

# OT trio odds (前日 or 確定 mixed)
trio_cache = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    trio_cache[rid][combo] = odds

# OZ win odds (前日)
win_odds_oz = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds_oz[rid] = {int(r[0]):r[1] for r in oz}

# SED confirmed win odds
win_odds_sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds > 0').fetchall():
    win_odds_sed[row[0]][row[1]] = row[2]

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

# For each race, compute:
# 1. OT trio odds (what we've been using)
# 2. Estimated confirmed trio odds (using SED/OZ win odds ratio)
# 3. Filter: PredBlend only (no market odds used in filter)

ALPHAS = [0.40, 0.50, 0.60, 0.70]
PRED_LIMITS = [5, 7, 10]
beta_v = 1.03; scale = 0.15

print("Computing race metrics...", flush=True)
# cache: (alpha, year) -> list of (pred_blend, ot_odds, estimated_confirmed_odds, hit)
cache = {}
for alpha in ALPHAS:
    for ty in TY:
        jc,hr,tp = build_train(f'{ty-1}-01-01', f'{ty}-01-01')
        results = []
        for rid,rd,vc,sf,dt in races_raw:
            if rd<f'{ty}-01-01' or rd>=f'{ty+1}-01-01': continue
            res_list=result_cache.get(rid,[])
            if len(res_list)<5: continue
            t3=[r['hn'] for r in res_list if r['fp']<=3]
            if len(t3)<3: continue
            om_oz=win_odds_oz.get(rid)
            if not om_oz: continue
            hl=sorted(om_oz.keys())
            if len(hl)<5: continue
            early=[om_oz[h] for h in hl]; trio=trio_cache.get(rid,{})
            sc=[score_m7(h,rid,vc,sf,dt,jc,hr,tp) for h in hl]
            mp=softmax(sc,scale); mkp=mktp(early,beta_v); bp=blendf(mp,mkp,alpha)
            rk=sorted(range(len(hl)),key=lambda i:-bp[i])
            top=sorted([hl[rk[0]],hl[rk[1]],hl[rk[2]]])
            combo=f'{top[0]}-{top[1]}-{top[2]}'
            ot_odds=trio.get(combo,0)
            if ot_odds<=0: continue

            # PredBlend (filter criterion - no leak)
            tp_b=harville_trio(bp,rk[0],rk[1],rk[2])
            pb=(1/tp_b)*0.75 if tp_b>0 else 9999

            hit=frozenset(top)==frozenset(t3[:3])

            # Estimate confirmed trio odds from win odds ratio
            # Method: ratio = product of (SED_odds/OZ_odds) for the 3 horses
            sed_odds = win_odds_sed.get(rid, {})
            ratios = []
            for h in top:
                oz_o = om_oz.get(h, 0)
                sed_o = sed_odds.get(h, 0)
                if oz_o > 0 and sed_o > 0:
                    ratios.append(sed_o / oz_o)
            if len(ratios) == 3:
                # Geometric mean of ratios applied to trio odds
                import functools, operator
                geo_ratio = (ratios[0] * ratios[1] * ratios[2]) ** (1/3)
                confirmed_trio_est = ot_odds * geo_ratio
            else:
                confirmed_trio_est = ot_odds  # fallback

            results.append((pb, ot_odds, confirmed_trio_est, hit, rd[:7]))
        cache[(alpha,ty)] = results
    print(f"  alpha={alpha} done", flush=True)

out = open(r'C:\Users\moribro2201\Desktop\m7_confirmed_odds_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

p('='*130)
p('=== M7 + PredBlend Filter: OT Odds vs Confirmed Odds Estimate ===')
p('='*130)
p()

# Compare OT payout vs confirmed payout
for alpha in ALPHAS:
    p(f'--- alpha={alpha} ---')
    p(f'  {"Filter":>12} | {"OT(前日/確定混在)":>20} {"Confirmed Est":>20} {"Diff":>8} | yearly OT -> yearly Confirmed')
    p(f'  {"-"*120}')

    for pred_max in PRED_LIMITS:
        # OT odds payout
        ot_yearly = {ty:{'b':0,'r':0,'h':0,'c':0} for ty in TY}
        cf_yearly = {ty:{'b':0,'r':0,'h':0,'c':0} for ty in TY}

        for ty in TY:
            for pb, ot, cf, hit, ym in cache[(alpha, ty)]:
                if pb > pred_max: continue
                ot_yearly[ty]['b'] += B; ot_yearly[ty]['c'] += 1
                cf_yearly[ty]['b'] += B; cf_yearly[ty]['c'] += 1
                if hit:
                    ot_yearly[ty]['r'] += B * ot; ot_yearly[ty]['h'] += 1
                    cf_yearly[ty]['r'] += B * cf; cf_yearly[ty]['h'] += 1

        ot_tb = sum(v['b'] for v in ot_yearly.values())
        ot_tr = sum(v['r'] for v in ot_yearly.values())
        cf_tb = sum(v['b'] for v in cf_yearly.values())
        cf_tr = sum(v['r'] for v in cf_yearly.values())
        ot_rr = ot_tr/ot_tb*100 if ot_tb>0 else 0
        cf_rr = cf_tr/cf_tb*100 if cf_tb>0 else 0
        rc = sum(v['c'] for v in ot_yearly.values())

        ot_yr = ' '.join(f'{ot_yearly[ty]["r"]/ot_yearly[ty]["b"]*100 if ot_yearly[ty]["b"]>0 else 0:>5.1f}%' for ty in TY)
        cf_yr = ' '.join(f'{cf_yearly[ty]["r"]/cf_yearly[ty]["b"]*100 if cf_yearly[ty]["b"]>0 else 0:>5.1f}%' for ty in TY)

        p(f'  PredB<={pred_max:>2}   | {ot_rr:>5.1f}% {rc:>5}R {sum(v["h"] for v in ot_yearly.values()):>4}hit | {cf_rr:>5.1f}% {rc:>5}R            {cf_rr-ot_rr:>+5.1f}pt | OT: {ot_yr}')
        p(f'  {"":>12} | {"":>20} {"":>20} {"":>8} | CF: {cf_yr}')
    p()

# Detailed: PredB<=5, alpha=0.50 monthly
p('='*130)
p('=== PredB<=5 alpha=0.50: Monthly OT vs Confirmed ===')
p('='*130)
p()

alpha = 0.50; pred_max = 5
monthly_ot = {}; monthly_cf = {}
for ty in TY:
    for pb, ot, cf, hit, ym in cache[(alpha, ty)]:
        if pb > pred_max: continue
        if ym not in monthly_ot: monthly_ot[ym] = {'b':0,'r':0}; monthly_cf[ym] = {'b':0,'r':0}
        monthly_ot[ym]['b'] += B; monthly_cf[ym]['b'] += B
        if hit:
            monthly_ot[ym]['r'] += B * ot
            monthly_cf[ym]['r'] += B * cf

p(f'  {"YearMon":>8} {"OT_RR":>7} {"CF_RR":>7} {"Diff":>6}')
p(f'  {"-"*35}')
for ym in sorted(monthly_ot.keys()):
    ot_rr = monthly_ot[ym]['r']/monthly_ot[ym]['b']*100
    cf_rr = monthly_cf[ym]['r']/monthly_cf[ym]['b']*100
    p(f'  {ym:>8} {ot_rr:>6.1f}% {cf_rr:>6.1f}% {cf_rr-ot_rr:>+5.1f}')

# Overall confirmed odds ratio for filtered races
p()
p('='*130)
p('=== Diagnostic: Confirmed/OT ratio for PredB<=5 races ===')
p('='*130)
p()
ratios_all = []
for ty in TY:
    for pb, ot, cf, hit, ym in cache[(0.50, ty)]:
        if pb > 5: continue
        if hit:
            ratios_all.append(cf/ot if ot>0 else 1.0)
if ratios_all:
    avg_ratio = sum(ratios_all)/len(ratios_all)
    sorted_r = sorted(ratios_all)
    med_ratio = sorted_r[len(sorted_r)//2]
    p(f'  Hit count: {len(ratios_all)}')
    p(f'  Avg confirmed/OT ratio: {avg_ratio:.4f}')
    p(f'  Median ratio: {med_ratio:.4f}')
    p(f'  Min: {min(ratios_all):.4f}, Max: {max(ratios_all):.4f}')
    # Distribution
    buckets = [(0,0.5),(0.5,0.7),(0.7,0.8),(0.8,0.9),(0.9,1.0),(1.0,1.1),(1.1,1.3),(1.3,2.0),(2.0,99)]
    p(f'  Distribution:')
    for lo,hi in buckets:
        cnt = sum(1 for r in ratios_all if lo<=r<hi)
        p(f'    {lo:.1f}-{hi:.1f}: {cnt} ({cnt/len(ratios_all)*100:.1f}%)')

# Final summary
p()
p('='*130)
p('=== Final Summary ===')
p('='*130)
p()
p(f'  {"Filter":>15} {"alpha":>6} | {"OT RR":>7} {"CF RR":>7} {"Diff":>7} | {"OT PnL":>12} {"CF PnL":>12}')
p(f'  {"-"*80}')
for alpha in ALPHAS:
    for pred_max in PRED_LIMITS:
        ot_b=0;ot_r=0;cf_b=0;cf_r=0;rc=0
        for ty in TY:
            for pb,ot,cf,hit,ym in cache[(alpha,ty)]:
                if pb>pred_max: continue
                ot_b+=B;cf_b+=B;rc+=1
                if hit: ot_r+=B*ot; cf_r+=B*cf
        ot_rr=ot_r/ot_b*100 if ot_b>0 else 0
        cf_rr=cf_r/cf_b*100 if cf_b>0 else 0
        p(f'  PredB<={pred_max:>2}      {alpha:.2f}  | {ot_rr:>6.1f}% {cf_rr:>6.1f}% {cf_rr-ot_rr:>+6.1f}pt | {ot_r-ot_b:>+11,.0f} {cf_r-cf_b:>+11,.0f}')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\m7_confirmed_odds_results.txt", flush=True)
