"""
指摘2: 払戻計算の楽観性監査
- OTオッズ（前日/確定混在）と実際の確定払戻の差を調査
- 人気3連複は締切にかけて買い込まれてオッズが下がるパターンの検証
- 確定単勝オッズ比率から三連複の確定/前日比率を推定

指摘4: OT異常値の明示的除外
- OT > 理論最大を除外するルール追加
"""
import sqlite3, math, sys
from collections import defaultdict
from itertools import permutations
sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

# === Part 1: OT1 vs OT2 の比率調査 ===
print("=== Part 1: OT1(前日) vs OT2(確定) のオッズ比較 ===", flush=True)

# Check import_log to see which races have OT1 vs OT2
# OT1 files = 前日, OT2 files = 確定
# Both write to odds table with bet_type='sanrenpuku'
# We need to check if we can distinguish them

# Actually, let's check: for races that have BOTH OT1 and OT2 imported,
# the OT2 would overwrite OT1 (INSERT OR REPLACE). So current data is mostly OT2.
# For races with only OT1 (before OT2 was downloaded), data is OT1.

# Let's check coverage by year
print("\n  Import log analysis:")
for year in range(2019, 2027):
    yy = str(year - 2000).zfill(2)
    ot1 = db.execute(f"SELECT COUNT(*) FROM import_log WHERE file_name LIKE 'OT1{yy}%'").fetchone()[0]
    ot2 = db.execute(f"SELECT COUNT(*) FROM import_log WHERE file_name LIKE 'OT2{yy}%'").fetchone()[0]
    print(f"    {year}: OT1={ot1} files, OT2={ot2} files")

# === Part 2: 確定単勝オッズ vs 前日単勝オッズの比率（馬券種別推定に使用）===
print("\n=== Part 2: 確定単勝/前日単勝 比率（人気帯別・年別）===", flush=True)

# OZ = 前日単勝オッズ (odds table, bet_type='win')
# SED = 確定単勝オッズ (results.win_odds)

# Compute ratio per popularity band AND per market odds of the trio combo
rows = db.execute('''
    SELECT r.race_id, r.horse_number, r.finish_position, r.popularity,
           o.odds as oz_odds, r.win_odds as sed_odds
    FROM results r
    JOIN odds o ON r.race_id = o.race_id AND CAST(o.combination AS INTEGER) = r.horse_number
    WHERE o.bet_type = 'win' AND r.win_odds IS NOT NULL AND o.odds IS NOT NULL
    AND o.odds > 0 AND r.win_odds > 0 AND r.win_odds < 999 AND o.odds < 999
    AND r.popularity IS NOT NULL
''').fetchall()

print(f"  Total pairs: {len(rows):,}")

# Group by popularity
from collections import defaultdict
pop_ratios = defaultdict(list)
for rid, hn, fp, pop, oz, sed in rows:
    pop_ratios[pop].append(sed / oz)

print(f"\n  {'Pop':>4} {'Count':>7} {'AvgRatio':>9} {'MedianR':>8} {'<0.8':>6} {'0.8-1.0':>7} {'1.0-1.2':>7} {'>1.2':>6}")
print(f"  {'-'*65}")
for pop in range(1, 11):
    ratios = pop_ratios.get(pop, [])
    if not ratios: continue
    avg = sum(ratios)/len(ratios)
    srt = sorted(ratios); med = srt[len(srt)//2]
    lt08 = sum(1 for r in ratios if r < 0.8) / len(ratios) * 100
    r08_10 = sum(1 for r in ratios if 0.8 <= r < 1.0) / len(ratios) * 100
    r10_12 = sum(1 for r in ratios if 1.0 <= r < 1.2) / len(ratios) * 100
    gt12 = sum(1 for r in ratios if r >= 1.2) / len(ratios) * 100
    print(f"  {pop:>4} {len(ratios):>7} {avg:>9.4f} {med:>8.4f} {lt08:>5.1f}% {r08_10:>6.1f}% {r10_12:>6.1f}% {gt12:>5.1f}%")

# === Part 3: PredB<=8で的中した馬の人気分布 ===
print("\n=== Part 3: PredB<=8 的中レースの馬の人気分布 ===", flush=True)

# Re-run M7 simulation to collect hit details
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,idm,total_index,rider_index,run_style FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es:
        entry_cache[rid] = {}
        for e in es: entry_cache[rid][e[0]] = {'hid':e[1],'jockey':e[2],'idm':e[3],'total':e[4],'rider':e[5],'run_style':e[6]}
result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight_diff,win_odds,popularity FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'weight_diff':row[4],'confirmed_odds':row[5],'popularity':row[6]})
race_cond = {}
for row in db.execute('SELECT race_id,track_condition FROM races').fetchall(): race_cond[row[0]] = row[1]
trio_cache = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall(): trio_cache[rid][combo] = odds
win_odds_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds_cache[rid] = {int(r[0]):r[1] for r in oz}

# SED confirmed win odds for ratio estimation
win_odds_sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds > 0').fetchall():
    win_odds_sed[row[0]][row[1]] = row[2]

TY = [2021,2022,2023,2024,2025,2026]; B = 10000

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

alpha=0.50; beta_v=1.03; scale=0.15; pred_max=8

# Collect hits with popularity info and OZ/SED ratio
print("\n  Running M7 to collect hit details...", flush=True)
hit_details = []  # (year, ot_odds, estimated_confirmed, top3_pops, top3_oz, top3_sed)

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
        tp_b=harville_trio(bp,rk[0],rk[1],rk[2])
        pb=(1/tp_b)*0.75 if tp_b>0 else 9999
        if pb>pred_max: continue
        hit=frozenset(top)==frozenset(t3[:3])
        if not hit: continue

        # Get popularity and odds ratios for the 3 horses
        pops = []
        oz_odds_list = []
        sed_odds_list = []
        for h in top:
            for r in res_list:
                if r['hn'] == h:
                    pops.append(r.get('popularity', 99))
                    break
            oz_odds_list.append(om.get(h, 0))
            sed_odds_list.append(win_odds_sed.get(rid, {}).get(h, 0))

        # Estimate confirmed trio odds
        ratios = []
        for oz_o, sed_o in zip(oz_odds_list, sed_odds_list):
            if oz_o > 0 and sed_o > 0:
                ratios.append(sed_o / oz_o)
        if len(ratios) == 3:
            geo_ratio = (ratios[0] * ratios[1] * ratios[2]) ** (1/3)
            est_confirmed = mo * geo_ratio
        else:
            est_confirmed = mo

        pops_clean = [p if p is not None else 99 for p in pops]
        hit_details.append((ty, mo, est_confirmed, sorted(pops_clean), oz_odds_list, sed_odds_list))

db.close()

print(f"  Collected {len(hit_details)} hits", flush=True)

# Analyze hit popularity distribution
print(f"\n  Top3 popularity distribution in hits:")
all_pops = []
for _, _, _, pops, _, _ in hit_details:
    all_pops.extend(pops)
pop_counts = defaultdict(int)
for p in all_pops:
    pop_counts[p] += 1
for p in sorted(pop_counts.keys()):
    print(f"    Pop {p}: {pop_counts[p]} ({pop_counts[p]/len(all_pops)*100:.1f}%)")

# Average OT odds and estimated confirmed for hits
avg_ot = sum(mo for _,mo,_,_,_,_ in hit_details) / len(hit_details)
avg_cf = sum(cf for _,_,cf,_,_,_ in hit_details) / len(hit_details)
print(f"\n  Average OT odds (hits): {avg_ot:.2f}")
print(f"  Average estimated confirmed odds (hits): {avg_cf:.2f}")
print(f"  Ratio (confirmed/OT): {avg_cf/avg_ot:.4f}")

# Year-by-year comparison
print(f"\n  Year-by-year OT vs Confirmed:")
print(f"  {'Year':>5} {'Hits':>5} {'AvgOT':>7} {'AvgCF':>7} {'Ratio':>7} {'OT_RR':>7} {'CF_RR':>7} {'Diff':>6}")
print(f"  {'-'*55}")
for ty in TY:
    yr_hits = [(mo, cf) for y, mo, cf, _, _, _ in hit_details if y == ty]
    if not yr_hits: continue
    yr_bets = sum(1 for a in [1] for y2, pb2 in [(1,1)]) # need to recalculate...
    # Use simpler calculation
    ot_total = sum(mo for mo, _ in yr_hits) * B
    cf_total = sum(cf for _, cf in yr_hits) * B
    avg_ot_yr = sum(mo for mo, _ in yr_hits) / len(yr_hits)
    avg_cf_yr = sum(cf for _, cf in yr_hits) / len(yr_hits)
    ratio = avg_cf_yr / avg_ot_yr if avg_ot_yr > 0 else 0
    print(f"  {ty:>5} {len(yr_hits):>5} {avg_ot_yr:>6.2f}x {avg_cf_yr:>6.2f}x {ratio:>6.4f}")

# Estimate total impact
print(f"\n  === Impact on total RR ===")
ot_payout = sum(mo * B for _, mo, _, _, _, _ in hit_details)
cf_payout = sum(cf * B for _, _, cf, _, _, _ in hit_details)
# Total bets for PB<=8 alpha=0.50 was 8094 races
total_bets = 8094 * B
ot_rr = ot_payout / total_bets * 100
cf_rr = cf_payout / total_bets * 100
print(f"  Total bets: {total_bets:,}")
print(f"  OT payout:  {ot_payout:,.0f} -> RR= hits contribute {ot_payout/total_bets*100:.1f}%")
print(f"  CF payout:  {cf_payout:,.0f} -> RR= hits contribute {cf_payout/total_bets*100:.1f}%")
print(f"  Difference: {cf_payout - ot_payout:+,.0f} ({(cf_rr - ot_rr):+.1f}pt)")
print(f"  Full RR (OT): 122.4% -> Full RR (CF est): {122.4 + (cf_rr - ot_rr):.1f}%")
