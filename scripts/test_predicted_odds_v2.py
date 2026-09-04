"""
予想オッズ計算方法の比較:
A. Harville(blended) - 現行方式
B. Harville(market only) - 市場確率からHarville
C. EV = blended_trio_prob * market_odds (期待値フィルタ)
D. 市場オッズそのまま (ベースライン)
E. predicted/market ratio (予想と市場の乖離率)
F. 市場単勝オッズのtop3合計 (シンプル指標)
"""
import sqlite3, math
from collections import defaultdict
from itertools import permutations

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
ec = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: ec[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}
tc = defaultdict(dict)
for rid, combo, odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='sanrenpuku'").fetchall():
    tc[rid][combo] = odds
TY = [2021,2022,2023,2024,2025,2026]; B = 10000

rd = {}
for ty in TY:
    ts = f'{ty-1}-01-01'; te = f'{ty}-01-01'
    jc = defaultdict(lambda:{'r':0,'w':0}); hr = defaultdict(list)
    for rid,rdt,vc,sf,dt in races:
        if rdt < ts or rdt >= te: continue
        res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
        for hn,fp,hid in res:
            ent = ec.get(rid,{}).get(hn,{}); jn = ent.get('jockey','')
            if jn: jc[jn]['r'] += 1; fp == 1 and jc[jn].__setitem__('w', jc[jn]['w']+1)
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
                if len(hr[hid]) > 20: hr[hid] = hr[hid][-20:]
    _jc, _hr = jc, hr
    def mk(jc_r, hr_r):
        def sc(h, rid, vc, sf, dt):
            b = 50.0; ent = ec.get(rid,{}).get(h,{}); hid = ent.get('hid',''); jn = ent.get('jockey','')
            jb = 0
            if jn and jn in jc_r and jc_r[jn]['r'] >= 20: jb = (jc_r[jn]['w']/jc_r[jn]['r']-0.08)*50
            hb = db_ = sb = vb = tb = 0
            if hid and hid in hr_r:
                rc = hr_r[hid]
                if len(rc) >= 2: hb = (6-sum(r['fp'] for r in rc[-5:])/len(rc[-5:]))*2
                dr = [r for r in rc if r['dist'] and abs(r['dist']-dt) <= 200]
                if len(dr) >= 2: db_ = (6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:]))*1.5
                sr = [r for r in rc if r['surface'] == sf]
                if len(sr) >= 2: sb = (6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:]))*1.5
                vr = [r for r in rc if r['venue'] == vc]
                if len(vr) >= 2: vb = (6-sum(r['fp'] for r in vr[-5:])/len(vr[-5:]))*1.0
                if len(rc) >= 3:
                    l3 = [r['fp'] for r in rc[-3:]]
                    if l3[-1] < l3[0]: tb = (l3[0]-l3[-1])*0.8
            return b+jb+hb+db_+sb+vb+tb
        return sc
    scorer = mk(_jc, _hr)
    rl = []
    for rid,rdt,vc,sf,dt in races:
        if rdt < f'{ty}-01-01' or rdt >= f'{ty+1}-01-01': continue
        res = db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
        if len(res) < 5: continue
        t3 = [r[0] for r in res if r[1] <= 3]
        if len(t3) < 3: continue
        oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
        if not oz: continue
        om = {int(r[0]):r[1] for r in oz}; hl = sorted(om.keys())
        if len(hl) < 5: continue
        early = [om[h] for h in hl]
        sc = [scorer(h, rid, vc, sf, dt) for h in hl]
        t3s = frozenset(t3[:3]); trio = tc.get(rid, {})
        rl.append((hl, sc, early, om, t3s, trio))
    rd[ty] = rl
db.close()
print("Data loaded.", flush=True)

def softmax(sc, scale):
    s = [(x-50)*scale for x in sc]; mx = max(s); e = [math.exp(x-mx) for x in s]; t = sum(e)
    return [x/t for x in e]
def mktp(odds, beta):
    inv = [1/o if o > 0 else 0 for o in odds]; s = sum(inv)
    if s == 0: return [1/len(odds)]*len(odds)
    raw = [i/s for i in inv]; pw = [p_**beta for p_ in raw]; ps = sum(pw)
    return [p_/ps for p_ in pw]
def blendf(m, mk, alpha):
    bl = [math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a, b in zip(m, mk)]
    s = sum(bl); return [p_/s for p_ in bl]

def harville_trio(probs, i, j, k):
    total = 0.0
    for perm in permutations([i, j, k]):
        a, b, c = perm
        s = sum(probs)
        if s <= 0: return 0
        p1 = probs[a] / s
        s2 = s - probs[a]
        if s2 <= 0: return 0
        p2 = probs[b] / s2
        s3 = s2 - probs[b]
        if s3 <= 0: return 0
        p3 = probs[c] / s3
        total += p1 * p2 * p3
    return total

alpha = 0.50; beta = 1.03; scale = 0.15

# For each race, compute all metrics
print("Computing metrics...", flush=True)
race_metrics = []  # list of dicts per year
for ty in TY:
    for hl, sc, early, om, t3s, trio in rd[ty]:
        n = len(hl)
        mp = softmax(sc, scale)
        mkp = mktp(early, beta)
        bp = blendf(mp, mkp, alpha)
        rk = sorted(range(n), key=lambda i: -bp[i])
        top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
        combo = f'{top[0]}-{top[1]}-{top[2]}'
        market_odds = trio.get(combo, 0)
        if market_odds <= 0: continue
        hit = frozenset(top) == t3s
        pay = B * market_odds if hit else 0

        # A. Harville from blended probs
        trio_prob_blend = harville_trio(bp, rk[0], rk[1], rk[2])
        pred_odds_blend = (1/trio_prob_blend) * 0.75 if trio_prob_blend > 0 else 9999

        # B. Harville from market probs only
        trio_prob_mkt = harville_trio(mkp, rk[0], rk[1], rk[2])
        pred_odds_mkt = (1/trio_prob_mkt) * 0.75 if trio_prob_mkt > 0 else 9999

        # C. EV = trio_prob_blend * market_odds
        ev = trio_prob_blend * market_odds if trio_prob_blend > 0 else 0

        # D. Market odds (direct)
        # already have market_odds

        # E. Ratio predicted/market
        ratio = pred_odds_blend / market_odds if market_odds > 0 else 9999

        # F. Top3 win odds sum (simple)
        top3_win_odds_sum = sum(om.get(h, 99) for h in top)

        race_metrics.append({
            'year': ty, 'hit': hit, 'pay': pay, 'market_odds': market_odds,
            'pred_blend': pred_odds_blend, 'pred_mkt': pred_odds_mkt,
            'ev': ev, 'ratio': ratio, 'win_sum': top3_win_odds_sum,
        })

print(f"  {len(race_metrics)} race-bets computed", flush=True)

out = open(r'C:\Users\moribro2201\Desktop\predicted_odds_v2_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s + '\n')

# === Diagnostic: correlation between predicted and market odds ===
p('=' * 100)
p('=== Diagnostic: Predicted vs Market Odds Distribution ===')
p('=' * 100)
p()

# Bucketize by market odds and show average predicted odds
mkt_buckets = [(0,3),(3,5),(5,7),(7,10),(10,15),(15,20),(20,30),(30,50),(50,100),(100,9999)]
p(f'  {"Market Odds":>15} {"Count":>6} {"Avg PredBlend":>13} {"Avg PredMkt":>11} {"Avg EV":>7} {"HitRate":>7} {"AvgRR":>6}')
p(f'  {"-"*75}')
for lo, hi in mkt_buckets:
    subset = [r for r in race_metrics if lo < r['market_odds'] <= hi]
    if not subset: continue
    avg_pb = sum(r['pred_blend'] for r in subset) / len(subset)
    avg_pm = sum(r['pred_mkt'] for r in subset) / len(subset)
    avg_ev = sum(r['ev'] for r in subset) / len(subset)
    hits = sum(1 for r in subset if r['hit'])
    hr = hits / len(subset) * 100
    tb = len(subset) * B
    tr = sum(r['pay'] for r in subset)
    rr = tr / tb * 100
    label = f'{lo}-{hi}' if hi < 9999 else f'{lo}+'
    p(f'  {label:>15} {len(subset):>6} {avg_pb:>13.1f} {avg_pm:>11.1f} {avg_ev:>7.3f} {hr:>6.1f}% {rr:>5.1f}%')

# === Compare filter methods ===
p()
p('=' * 100)
p('=== Filter Method Comparison (alpha=0.50) ===')
p('=' * 100)

def test_filter(metrics, filter_fn, label):
    yearly = {}
    for r in metrics:
        if not filter_fn(r): continue
        y = r['year']
        if y not in yearly: yearly[y] = {'b':0,'r':0,'h':0,'c':0}
        yearly[y]['b'] += B; yearly[y]['r'] += r['pay']; yearly[y]['c'] += 1
        if r['hit']: yearly[y]['h'] += 1
    tb = sum(v['b'] for v in yearly.values())
    tr = sum(v['r'] for v in yearly.values())
    rc = sum(v['c'] for v in yearly.values())
    rr = tr/tb*100 if tb > 0 else 0
    parts = []
    for ty in TY:
        if ty in yearly and yearly[ty]['b'] > 0:
            yrr = yearly[ty]['r']/yearly[ty]['b']*100
            parts.append(f'{yrr:>5.1f}%({yearly[ty]["c"]:>3}R)')
        else:
            parts.append(f'  {"---":>9}')
    return rr, rc, parts

p()
p(f'  {"Method":>30} {"TotalRR":>7} {"R":>5} | {"2021":>11} {"2022":>11} {"2023":>11} {"2024":>11} {"2025":>11} {"2026":>11}')
p(f'  {"-"*115}')

filters = [
    # Market odds filters
    ('D. Market <= 5',   lambda r: r['market_odds'] <= 5),
    ('D. Market <= 7',   lambda r: r['market_odds'] <= 7),
    ('D. Market <= 10',  lambda r: r['market_odds'] <= 10),
    ('D. Market <= 15',  lambda r: r['market_odds'] <= 15),
    ('D. Market <= 20',  lambda r: r['market_odds'] <= 20),
    ('', None),
    # Harville blended (current)
    ('A. HarvBlend <= 5',  lambda r: r['pred_blend'] <= 5),
    ('A. HarvBlend <= 7',  lambda r: r['pred_blend'] <= 7),
    ('A. HarvBlend <= 10', lambda r: r['pred_blend'] <= 10),
    ('A. HarvBlend <= 15', lambda r: r['pred_blend'] <= 15),
    ('', None),
    # Harville from market probs
    ('B. HarvMkt <= 5',  lambda r: r['pred_mkt'] <= 5),
    ('B. HarvMkt <= 7',  lambda r: r['pred_mkt'] <= 7),
    ('B. HarvMkt <= 10', lambda r: r['pred_mkt'] <= 10),
    ('B. HarvMkt <= 15', lambda r: r['pred_mkt'] <= 15),
    ('', None),
    # EV filter
    ('C. EV >= 1.50',  lambda r: r['ev'] >= 1.50),
    ('C. EV >= 1.20',  lambda r: r['ev'] >= 1.20),
    ('C. EV >= 1.10',  lambda r: r['ev'] >= 1.10),
    ('C. EV >= 1.05',  lambda r: r['ev'] >= 1.05),
    ('C. EV >= 1.00',  lambda r: r['ev'] >= 1.00),
    ('C. EV >= 0.90',  lambda r: r['ev'] >= 0.90),
    ('', None),
    # Ratio (predicted/market < threshold = model thinks it's cheaper than market)
    ('E. Ratio < 0.5',  lambda r: r['ratio'] < 0.5),
    ('E. Ratio < 0.7',  lambda r: r['ratio'] < 0.7),
    ('E. Ratio < 0.8',  lambda r: r['ratio'] < 0.8),
    ('E. Ratio < 1.0',  lambda r: r['ratio'] < 1.0),
    ('E. Ratio < 1.2',  lambda r: r['ratio'] < 1.2),
    ('', None),
    # Win odds sum
    ('F. WinSum <= 5',  lambda r: r['win_sum'] <= 5),
    ('F. WinSum <= 8',  lambda r: r['win_sum'] <= 8),
    ('F. WinSum <= 10', lambda r: r['win_sum'] <= 10),
    ('F. WinSum <= 15', lambda r: r['win_sum'] <= 15),
    ('F. WinSum <= 20', lambda r: r['win_sum'] <= 20),
    ('', None),
    # Combined: EV + Market
    ('EV>=1.05 & Mkt<=10', lambda r: r['ev'] >= 1.05 and r['market_odds'] <= 10),
    ('EV>=1.10 & Mkt<=10', lambda r: r['ev'] >= 1.10 and r['market_odds'] <= 10),
    ('EV>=1.10 & Mkt<=15', lambda r: r['ev'] >= 1.10 and r['market_odds'] <= 15),
    ('EV>=1.05 & Mkt<=15', lambda r: r['ev'] >= 1.05 and r['market_odds'] <= 15),
    ('Ratio<0.8 & Mkt<=10', lambda r: r['ratio'] < 0.8 and r['market_odds'] <= 10),
    ('', None),
    ('ALL (no filter)',  lambda r: True),
]

for label, fn in filters:
    if fn is None:
        p()
        continue
    rr, rc, parts = test_filter(race_metrics, fn, label)
    p(f'  {label:>30} {rr:>6.1f}% {rc:>5} | {" ".join(parts)}')

out.close()
print(f"\nDone! C:\\Users\\moribro2201\\Desktop\\predicted_odds_v2_results.txt", flush=True)
