"""
M7モデルで全券種の回収率をシミュレーション
三連複以外でもプラスになる賭け方を探す
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

# Load odds lazily - only win odds in memory
win_odds_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: win_odds_cache[rid] = {int(r[0]):r[1] for r in oz}

def get_odds(race_id, bet_type, combination):
    row = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",
                     (race_id, bet_type, combination)).fetchone()
    return row[0] if row and row[0] > 0 else 0

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

alpha=0.50; beta_v=1.03; scale=0.15

# Collect M7 rankings per race
print("Computing M7 rankings...", flush=True)
race_rankings = {}  # race_id -> (ranked_horse_numbers[], blended_probs[], pred_blend, top3_set)

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
        early=[om[h] for h in hl]
        sc=[score_m7(h,rid,vc,sf,dt,jc,hr,tp) for h in hl]
        mp=softmax(sc,scale); mkp=mktp(early,beta_v); bp=blendf(mp,mkp,alpha)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        ranked = [hl[r] for r in rk]
        probs = [bp[r] for r in rk]

        # PredBlend for trio filter
        if len(rk) >= 3:
            tp_b = harville_stern(bp, rk[0], rk[1], rk[2])
            pb = (1/tp_b)*0.75 if tp_b > 0 else 9999
        else:
            pb = 9999

        # Actual results
        actual_top1 = res_list[0]['hn'] if res_list else None
        actual_top2 = res_list[1]['hn'] if len(res_list) > 1 else None
        actual_top3 = set(r['hn'] for r in res_list if r['fp'] <= 3)

        race_rankings[rid] = {
            'date': rd, 'ranked': ranked, 'probs': probs, 'pb': pb,
            'actual_top1': actual_top1, 'actual_top2': actual_top2,
            'actual_top3': actual_top3,
        }

print(f"  {len(race_rankings)} races ranked", flush=True)

# Define bet strategies
def simulate_bets(filter_pb=None):
    results = {}

    for label, check_hit, get_combo, bet_type in [
        # Single bets
        ('単勝 ◎', lambda r: r['actual_top1'] == r['ranked'][0], lambda r: str(r['ranked'][0]), 'win'),
        ('複勝 ◎', lambda r: r['ranked'][0] in r['actual_top3'], lambda r: str(r['ranked'][0]), 'place'),
        ('複勝 ○', lambda r: r['ranked'][1] in r['actual_top3'], lambda r: str(r['ranked'][1]), 'place'),

        # Pair bets
        ('馬連 ◎○', lambda r: set(r['ranked'][:2]) == set([r['actual_top1'], r['actual_top2']]) if r['actual_top1'] and r['actual_top2'] else False,
         lambda r: '-'.join(str(x) for x in sorted(r['ranked'][:2])), 'umaren'),
        ('ワイド ◎○', lambda r: r['ranked'][0] in r['actual_top3'] and r['ranked'][1] in r['actual_top3'],
         lambda r: '-'.join(str(x) for x in sorted(r['ranked'][:2])), 'wide'),
        ('ワイド ◎▲', lambda r: r['ranked'][0] in r['actual_top3'] and r['ranked'][2] in r['actual_top3'],
         lambda r: '-'.join(str(x) for x in sorted([r['ranked'][0], r['ranked'][2]])), 'wide'),
        ('馬単 ◎→○', lambda r: r['ranked'][0] == r['actual_top1'] and r['ranked'][1] == r['actual_top2'],
         lambda r: f"{r['ranked'][0]}-{r['ranked'][1]}", 'umatan'),

        # Trio bets
        ('三連複 ◎○▲', lambda r: set(r['ranked'][:3]) == r['actual_top3'],
         lambda r: '-'.join(str(x) for x in sorted(r['ranked'][:3])), 'sanrenpuku'),
        ('三連単 ◎→○→▲', lambda r: r['ranked'][0]==r['actual_top1'] and r['ranked'][1]==r['actual_top2'] and r['ranked'][2] in r['actual_top3'] and len(r['actual_top3'])==3 and list(sorted(r['actual_top3']))==list(sorted(r['ranked'][:3])),
         lambda r: f"{r['ranked'][0]}-{r['ranked'][1]}-{r['ranked'][2]}", 'sanrentan'),
    ]:
        yearly = {y:{'b':0,'r':0,'h':0,'c':0} for y in TY}
        for rid, rdata in race_rankings.items():
            if filter_pb and rdata['pb'] > filter_pb: continue
            year = int('20' + rdata['date'][0:2]) if rdata['date'][0:2].isdigit() else int(rdata['date'][:4])
            if year not in yearly: continue

            combo = get_combo(rdata)
            odds_val = get_odds(rid, bet_type, combo)
            if odds_val <= 0 or odds_val > 500: continue

            hit = check_hit(rdata)
            yearly[year]['b'] += B; yearly[year]['c'] += 1
            if hit:
                yearly[year]['r'] += int(B * odds_val)
                yearly[year]['h'] += 1

        tb = sum(v['b'] for v in yearly.values())
        tr = sum(v['r'] for v in yearly.values())
        hits = sum(v['h'] for v in yearly.values())
        rc = sum(v['c'] for v in yearly.values())
        rr = tr/tb*100 if tb > 0 else 0
        hr_pct = hits/rc*100 if rc > 0 else 0
        yr_rrs = []
        for y in TY:
            if yearly[y]['b'] > 0:
                yr_rrs.append(yearly[y]['r']/yearly[y]['b']*100)
            else:
                yr_rrs.append(0)
        results[label] = {'rr': rr, 'rc': rc, 'hits': hits, 'hr': hr_pct, 'yearly': yr_rrs}

    # Multi-point bets
    for label, get_combos, bet_type, points in [
        ('ワイド ◎流し3点', lambda r: ['-'.join(str(x) for x in sorted([r['ranked'][0], r['ranked'][i]])) for i in range(1,4)], 'wide', 3),
        ('馬連 ◎流し3点', lambda r: ['-'.join(str(x) for x in sorted([r['ranked'][0], r['ranked'][i]])) for i in range(1,4)], 'umaren', 3),
        ('三連複 ◎○▲△BOX 4点', lambda r: ['-'.join(str(x) for x in sorted([r['ranked'][i],r['ranked'][j],r['ranked'][k]])) for i in range(4) for j in range(i+1,4) for k in range(j+1,4)], 'sanrenpuku', 4),
        ('馬単 ◎→○,◎→▲ 2点', lambda r: [f"{r['ranked'][0]}-{r['ranked'][1]}", f"{r['ranked'][0]}-{r['ranked'][2]}"], 'umatan', 2),
    ]:
        yearly = {y:{'b':0,'r':0,'h':0,'c':0} for y in TY}
        for rid, rdata in race_rankings.items():
            if filter_pb and rdata['pb'] > filter_pb: continue
            year = int('20' + rdata['date'][0:2]) if rdata['date'][0:2].isdigit() else int(rdata['date'][:4])
            if year not in yearly: continue

            combos = get_combos(rdata)
            total_bet = 0; total_pay = 0; any_hit = False
            for combo in combos:
                odds_val = get_odds(rid, bet_type, combo)
                if odds_val <= 0 or odds_val > 500: continue
                total_bet += B
                # Check hit for this specific combo
                parts = combo.replace('→','-').split('-')
                nums = [int(x) for x in parts]
                hit = False
                if bet_type == 'wide':
                    hit = all(n in rdata['actual_top3'] for n in nums)
                elif bet_type == 'umaren':
                    hit = rdata['actual_top1'] in nums and rdata['actual_top2'] in nums and len(nums)==2
                elif bet_type == 'sanrenpuku':
                    hit = set(nums) == rdata['actual_top3']
                elif bet_type == 'umatan':
                    hit = nums[0] == rdata['actual_top1'] and nums[1] == rdata['actual_top2']
                if hit:
                    total_pay += int(B * odds_val)
                    any_hit = True

            if total_bet > 0:
                yearly[year]['b'] += total_bet
                yearly[year]['c'] += 1
                yearly[year]['r'] += total_pay
                if any_hit: yearly[year]['h'] += 1

        tb = sum(v['b'] for v in yearly.values())
        tr = sum(v['r'] for v in yearly.values())
        hits = sum(v['h'] for v in yearly.values())
        rc = sum(v['c'] for v in yearly.values())
        rr = tr/tb*100 if tb > 0 else 0
        hr_pct = hits/rc*100 if rc > 0 else 0
        yr_rrs = []
        for y in TY:
            if yearly[y]['b'] > 0:
                yr_rrs.append(yearly[y]['r']/yearly[y]['b']*100)
            else:
                yr_rrs.append(0)
        results[label] = {'rr': rr, 'rc': rc, 'hits': hits, 'hr': hr_pct, 'yearly': yr_rrs}

    return results

# Run simulations
print("\n=== All races (no filter) ===", flush=True)
all_results = simulate_bets(filter_pb=None)

print("\n=== PredBlend <= 8 filter ===", flush=True)
pb8_results = simulate_bets(filter_pb=8)

print("\n=== PredBlend <= 5 filter ===", flush=True)
pb5_results = simulate_bets(filter_pb=5)

# Output
out = open(r'C:\Users\moribro2201\Desktop\bet_type_simulation.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

for filter_name, results in [('全レース', all_results), ('PredBlend<=8', pb8_results), ('PredBlend<=5', pb5_results)]:
    p(f'\n{"="*120}')
    p(f'=== {filter_name} ===')
    p(f'{"="*120}')
    p()

    # Sort by RR desc
    sorted_bets = sorted(results.items(), key=lambda x: -x[1]['rr'])
    p(f'  {"賭け方":>25} {"回収率":>7} {"R数":>7} {"的中":>5} {"的中率":>7} | {"2021":>7} {"2022":>7} {"2023":>7} {"2024":>7} {"2025":>7} {"2026":>7}')
    p(f'  {"-"*110}')
    for label, d in sorted_bets:
        yr = ' '.join(f'{r:>6.0f}%' for r in d['yearly'])
        marker = ' <<<' if d['rr'] >= 100 else ''
        p(f'  {label:>25} {d["rr"]:>6.1f}% {d["rc"]:>7} {d["hits"]:>5} {d["hr"]:>6.1f}% | {yr}{marker}')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\bet_type_simulation.txt", flush=True)
