"""
段階的ベットアップ戦略シミュレーション
初期20万 → 残高に応じてベット額を段階的に上げる → MAX2万円
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
TY = [2021,2022,2023,2024,2025,2026]
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

print("Collecting bets...", flush=True)
all_bets = []
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
        all_bets.append((rd, rid, hit, mo))
all_bets.sort(key=lambda x: (x[0], x[1]))
print(f"  {len(all_bets)} bets", flush=True)

INITIAL = 200000

# Step-up table candidates
# Rule: bet = balance / safety_divisor, rounded to 100, capped at max_bet
# safety_divisor = 45 (max consecutive losses) * 1.5 safety ≈ 67

step_tables = {
    'A: Conservative': [
        # (min_balance, bet_amount)
        (0,        1000),
        (200000,   2000),
        (400000,   3000),
        (600000,   5000),
        (1000000,  7000),
        (1500000, 10000),
        (2500000, 15000),
        (4000000, 20000),
    ],
    'B: Moderate': [
        (0,        2000),
        (200000,   3000),
        (350000,   5000),
        (600000,   7000),
        (1000000, 10000),
        (1500000, 15000),
        (2500000, 20000),
    ],
    'C: Aggressive': [
        (0,        3000),
        (200000,   5000),
        (400000,   7000),
        (700000,  10000),
        (1200000, 15000),
        (2000000, 20000),
    ],
    'D: Dynamic 3%': None,  # special: 3% of balance, max 20000
    'E: Dynamic 2%': None,  # special: 2% of balance, max 20000
    'F: Fixed 3000': None,  # baseline
}

def get_bet(strategy_name, table, balance):
    if strategy_name == 'D: Dynamic 3%':
        return min(20000, max(100, int(balance * 0.03 / 100) * 100))
    elif strategy_name == 'E: Dynamic 2%':
        return min(20000, max(100, int(balance * 0.02 / 100) * 100))
    elif strategy_name == 'F: Fixed 3000':
        return 3000
    else:
        bet = 1000
        for min_bal, amt in table:
            if balance >= min_bal:
                bet = amt
        return min(bet, balance)

def simulate(bets, strategy_name, table):
    balance = INITIAL
    peak = INITIAL
    max_dd = 0; min_balance = INITIAL
    monthly = defaultdict(lambda: {'start':0,'end':0,'bets':0,'hits':0,'bet_sizes':[]})
    level_changes = []

    prev_bet_size = 0
    for date, rid, hit, odds in bets:
        ym = date[:7]
        if monthly[ym]['bets'] == 0:
            monthly[ym]['start'] = balance

        bet = get_bet(strategy_name, table, balance)
        bet = min(bet, balance)
        if bet <= 0: break

        if bet != prev_bet_size:
            level_changes.append((date, balance, prev_bet_size, bet))
            prev_bet_size = bet

        balance -= bet
        if hit:
            balance += int(bet * odds)
            monthly[ym]['hits'] += 1

        monthly[ym]['bets'] += 1
        monthly[ym]['end'] = balance
        monthly[ym]['bet_sizes'].append(bet)

        if balance > peak: peak = balance
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
        if balance < min_balance: min_balance = balance

    return {
        'final': balance, 'pnl': balance - INITIAL,
        'peak': peak, 'min': min_balance, 'max_dd': max_dd,
        'monthly': dict(monthly), 'level_changes': level_changes,
    }

print("Running simulations...", flush=True)
results = {}
for name, table in step_tables.items():
    results[name] = simulate(all_bets, name, table)

out = open(r'C:\Users\moribro2201\Desktop\budget_stepup.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

p('='*100)
p(f'=== 段階的ベットアップ戦略 (初期20万, MAX2万円/R) ===')
p('='*100)

# Summary
p()
p(f'  {"戦略":>20} {"最終残高":>12} {"損益":>12} {"最大DD":>7} {"最低残高":>10}')
p(f'  {"-"*65}')
for name in step_tables:
    r = results[name]
    p(f'  {name:>20} {r["final"]:>11,}円 {r["pnl"]:>+11,}円 {r["max_dd"]:>5.1f}% {r["min"]:>9,}円')

# Details for each strategy
for name in ['A: Conservative', 'B: Moderate', 'C: Aggressive']:
    r = results[name]
    table = step_tables[name]
    p(f'\n{"="*100}')
    p(f'=== {name} ===')
    p(f'{"="*100}')

    # Step-up table
    p(f'\n  ベットアップルール:')
    p(f'  {"残高":>12} {"ベット額":>10}')
    p(f'  {"-"*25}')
    for min_bal, amt in table:
        p(f'  {min_bal:>11,}円 {amt:>9,}円')

    # Level change history
    p(f'\n  ベット額変更履歴（主要）:')
    p(f'  {"日付":>12} {"残高":>12} {"旧":>8} {"新":>8}')
    p(f'  {"-"*45}')
    shown = set()
    for date, bal, old, new in r['level_changes']:
        key = new
        if key not in shown:
            shown.add(key)
            p(f'  {date:>12} {bal:>11,}円 {old:>7,}円 {new:>7,}円')

    # Yearly summary
    p(f'\n  年別損益:')
    p(f'  {"年":>5} {"年初残高":>12} {"年末残高":>12} {"損益":>12} {"平均ベット":>10}')
    p(f'  {"-"*55}')
    for year in TY:
        yr_months = {k:v for k,v in r['monthly'].items() if k.startswith(str(year))}
        if not yr_months: continue
        first = sorted(yr_months.keys())[0]
        last = sorted(yr_months.keys())[-1]
        yr_start = yr_months[first]['start']
        yr_end = yr_months[last]['end']
        all_sizes = []
        for v in yr_months.values(): all_sizes.extend(v['bet_sizes'])
        avg_bet = sum(all_sizes)/len(all_sizes) if all_sizes else 0
        p(f'  {year:>5} {yr_start:>11,}円 {yr_end:>11,}円 {yr_end-yr_start:>+11,}円 {avg_bet:>9,.0f}円')

    # Monthly detail
    p(f'\n  月別推移:')
    p(f'  {"年月":>8} {"月初":>12} {"月末":>12} {"損益":>10} {"R数":>4} {"的中":>4} {"平均bet":>8}')
    p(f'  {"-"*65}')
    for ym in sorted(r['monthly'].keys()):
        m = r['monthly'][ym]
        if m['bets'] == 0: continue
        mpnl = m['end'] - m['start']
        avg_b = sum(m['bet_sizes'])/len(m['bet_sizes']) if m['bet_sizes'] else 0
        p(f'  {ym:>8} {m["start"]:>11,}円 {m["end"]:>11,}円 {mpnl:>+9,}円 {m["bets"]:>4} {m["hits"]:>4} {avg_b:>7,.0f}円')

# Recommendation
p(f'\n{"="*100}')
p(f'=== 推奨: B: Moderate ===')
p(f'{"="*100}')
p()
r = results['B: Moderate']
p(f'  初期資金: 200,000円 → 最終: {r["final"]:,}円 ({r["pnl"]:+,}円)')
p(f'  最大DD: {r["max_dd"]:.1f}%, 最低残高: {r["min"]:,}円')
p()
p(f'  ステップアップルール:')
p(f'  ┌──────────────┬──────────┬────────────────────┐')
p(f'  │  残高         │ ベット額 │ 意味               │')
p(f'  ├──────────────┼──────────┼────────────────────┤')
for min_bal, amt, desc in [
    (0, 2000, '開始直後・回復時'),
    (200000, 3000, '元本回復'),
    (350000, 5000, '利益+15万'),
    (600000, 7000, '元本3倍'),
    (1000000, 10000, '100万到達'),
    (1500000, 15000, '150万到達'),
    (2500000, 20000, '250万到達（MAX）'),
]:
    p(f'  │ {min_bal:>11,}円 │ {amt:>7,}円 │ {desc:<18} │')
p(f'  └──────────────┴──────────┴────────────────────┘')
p()
p(f'  ルール: 残高がステップの閾値を超えたらベット額を上げる')
p(f'  下がった場合は自動的にベット額も下がる（リスク管理）')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\budget_stepup.txt", flush=True)
