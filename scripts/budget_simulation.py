"""
予算20万円でのM7 v25運用シミュレーション
- 固定額 vs Kelly vs 資金比例
- 破産確率・最大ドローダウン・月別収支推移
- レース単位で時系列シミュレーション
"""
import sqlite3, math, sys, random
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
trio_hjc = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku_hjc' AND odds>0").fetchall(): trio_hjc[rid][combo] = odds
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

# Collect all bets chronologically
print("Collecting all M7 v25 bets chronologically...", flush=True)
all_bets = []  # (date, race_id, hit, odds, trio_prob, pred_blend)
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
        odds_hjc=trio_hjc.get(rid,{}).get(combo,mo)
        all_bets.append((rd, rid, hit, odds_hjc, tp_b, pb))

all_bets.sort(key=lambda x: (x[0], x[1]))
print(f"  Total bets: {len(all_bets)}", flush=True)

# === Strategy simulations ===
INITIAL = 200000

def simulate(bets, strategy_fn, label):
    """strategy_fn(balance, odds, trio_prob) -> bet_amount"""
    balance = INITIAL
    peak = INITIAL
    max_dd = 0
    min_balance = INITIAL
    history = []  # (date, balance)
    monthly = defaultdict(lambda: {'start':0,'end':0,'bets':0,'hits':0})
    bust = False

    for i, (date, rid, hit, odds, tp, pb) in enumerate(bets):
        ym = date[:7]
        if monthly[ym]['bets'] == 0:
            monthly[ym]['start'] = balance

        bet_amount = strategy_fn(balance, odds, tp)
        bet_amount = min(bet_amount, balance)  # can't bet more than balance
        bet_amount = max(0, int(bet_amount / 100) * 100)  # round to 100

        if bet_amount <= 0:
            if balance <= 0:
                bust = True
                break
            continue

        balance -= bet_amount
        if hit:
            balance += int(bet_amount * odds)
            monthly[ym]['hits'] += 1

        monthly[ym]['bets'] += 1
        monthly[ym]['end'] = balance

        if balance > peak: peak = balance
        dd = (peak - balance) / peak * 100 if peak > 0 else 0
        if dd > max_dd: max_dd = dd
        if balance < min_balance: min_balance = balance

        history.append((date, balance))

    return {
        'label': label,
        'final': balance,
        'pnl': balance - INITIAL,
        'peak': peak,
        'min': min_balance,
        'max_dd': max_dd,
        'bust': bust,
        'history': history,
        'monthly': dict(monthly),
    }

# Strategy definitions
strategies = [
    ('固定1,000円/R', lambda b, o, tp: 1000),
    ('固定2,000円/R', lambda b, o, tp: 2000),
    ('固定3,000円/R', lambda b, o, tp: 3000),
    ('固定5,000円/R', lambda b, o, tp: 5000),
    ('固定10,000円/R', lambda b, o, tp: 10000),
    ('資金1%/R', lambda b, o, tp: b * 0.01),
    ('資金2%/R', lambda b, o, tp: b * 0.02),
    ('資金3%/R', lambda b, o, tp: b * 0.03),
    ('資金5%/R', lambda b, o, tp: b * 0.05),
    ('1/4 Kelly', lambda b, o, tp: b * max(0, (tp * o - 1) / (o - 1)) * 0.25 if o > 1 else 0),
    ('1/8 Kelly', lambda b, o, tp: b * max(0, (tp * o - 1) / (o - 1)) * 0.125 if o > 1 else 0),
]

print("\nRunning strategy simulations...", flush=True)
results = []
for label, fn in strategies:
    r = simulate(all_bets, fn, label)
    results.append(r)

# Output
out = open(r'C:\Users\moribro2201\Desktop\budget_simulation.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

p('='*100)
p(f'=== M7 v25 予算20万円 運用シミュレーション ({len(all_bets)}R, 2021-2026) ===')
p('='*100)

# Summary table
p()
p(f'  {"戦略":>16} {"最終残高":>12} {"損益":>12} {"最大DD":>7} {"最低残高":>10} {"破産":>4}')
p(f'  {"-"*70}')
for r in results:
    bust = "YES" if r['bust'] else "no"
    p(f'  {r["label"]:>16} {r["final"]:>11,}円 {r["pnl"]:>+11,}円 {r["max_dd"]:>5.1f}% {r["min"]:>9,}円 {bust:>4}')

# Best strategy details
p()
p('='*100)
p('=== 推奨戦略の詳細 ===')
p('='*100)

for label_filter in ['固定3,000円/R', '資金2%/R', '1/4 Kelly']:
    r = [x for x in results if x['label'] == label_filter][0]
    p(f'\n--- {r["label"]} ---')
    p(f'  初期資金: {INITIAL:,}円')
    p(f'  最終残高: {r["final"]:,}円')
    p(f'  損益: {r["pnl"]:+,}円')
    p(f'  最大DD: {r["max_dd"]:.1f}%')
    p(f'  最低残高: {r["min"]:,}円')
    p(f'  破産: {"YES" if r["bust"] else "no"}')

    # Monthly P&L
    p(f'\n  月別残高推移:')
    p(f'  {"年月":>8} {"月初":>10} {"月末":>10} {"月間損益":>10} {"R数":>4} {"的中":>4}')
    p(f'  {"-"*55}')
    for ym in sorted(r['monthly'].keys()):
        m = r['monthly'][ym]
        if m['bets'] == 0: continue
        month_pnl = m['end'] - m['start']
        p(f'  {ym:>8} {m["start"]:>9,}円 {m["end"]:>9,}円 {month_pnl:>+9,}円 {m["bets"]:>4} {m["hits"]:>4}')

    # Yearly summary
    p(f'\n  年別損益:')
    for year in TY:
        yr_months = {k:v for k,v in r['monthly'].items() if k.startswith(str(year))}
        if not yr_months: continue
        first = sorted(yr_months.keys())[0]
        last = sorted(yr_months.keys())[-1]
        yr_pnl = yr_months[last]['end'] - yr_months[first]['start']
        yr_bets = sum(v['bets'] for v in yr_months.values())
        yr_hits = sum(v['hits'] for v in yr_months.values())
        p(f'    {year}: {yr_pnl:>+10,}円 ({yr_bets}R {yr_hits}的中)')

# Consecutive losses analysis
p()
p('='*100)
p('=== 連敗分析 ===')
p('='*100)
p()

max_streak = 0; current_streak = 0; streaks = []
for _, _, hit, _, _, _ in all_bets:
    if not hit:
        current_streak += 1
        if current_streak > max_streak: max_streak = current_streak
    else:
        if current_streak > 0: streaks.append(current_streak)
        current_streak = 0
if current_streak > 0: streaks.append(current_streak)

p(f'  最大連敗: {max_streak}連敗')
p(f'  10連敗以上: {sum(1 for s in streaks if s >= 10)}回')
p(f'  15連敗以上: {sum(1 for s in streaks if s >= 15)}回')
p(f'  20連敗以上: {sum(1 for s in streaks if s >= 20)}回')
p(f'  平均連敗: {sum(streaks)/len(streaks):.1f}')

# Required capital analysis
p()
p('='*100)
p('=== 必要資金分析（破産しない最低資金）===')
p('='*100)
p()
p(f'  {"固定額":>10} {"最低必要資金":>14} {"理由"}')
p(f'  {"-"*50}')
for bet_size in [1000, 2000, 3000, 5000, 10000]:
    # Minimum capital = bet_size * max_consecutive_losses * 1.5 (safety margin)
    min_capital = bet_size * max_streak
    safe_capital = int(min_capital * 1.5)
    p(f'  {bet_size:>9,}円 {safe_capital:>13,}円  {max_streak}連敗×{bet_size:,}×1.5')

p(f'\n  予算20万円での推奨:')
safe_bet = int(INITIAL / max_streak / 1.5 / 100) * 100
p(f'    最大安全ベット額: {safe_bet:,}円/R')
p(f'    根拠: 20万÷{max_streak}連敗÷1.5倍安全率 = {safe_bet:,}円')
p(f'    年間期待利益: {int(safe_bet * len(all_bets)/6 * 0.316):,}円 (890R×{safe_bet:,}×31.6%)')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\budget_simulation.txt", flush=True)
