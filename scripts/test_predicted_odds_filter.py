"""
予想オッズフィルタ: モデルのブレンド確率からHarvilleモデルで三連複確率を推定し、
その予想オッズでフィルタリング（実際のオッズは使わない）
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
            ent = ec.get(rid,{}).get(hn,{})
            jn = ent.get('jockey','')
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

def harville_trio_prob(bp, idx_i, idx_j, idx_k):
    """Harville model: P(trio {i,j,k}) = sum of all 6 orderings"""
    probs = list(bp)
    total = 0.0
    for perm in permutations([idx_i, idx_j, idx_k]):
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

ALPHAS = [0.0, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70]
PRED_ODDS_LIMITS = [3, 5, 7, 10, 15, 20, 30, 9999]
MARKET_ODDS_LIMITS = [10, 9999]
beta = 1.03; scale = 0.15

# Pre-cache: for each alpha, year, race -> (predicted_odds, market_odds, hit, pay)
print("Building cache with Harville trio probs...", flush=True)
cache = {}
for alpha in ALPHAS:
    for ty in TY:
        results = []
        for hl, sc, early, om, t3s, trio in rd[ty]:
            n = len(hl)
            mp = softmax(sc, scale); mkp = mktp(early, beta)
            if alpha <= 0.001: bp = mkp
            elif alpha >= 0.999: bp = mp
            else: bp = blendf(mp, mkp, alpha)
            rk = sorted(range(n), key=lambda i: -bp[i])
            top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
            combo = f'{top[0]}-{top[1]}-{top[2]}'
            market_odds = trio.get(combo, 0)
            if market_odds <= 0: continue

            # Predicted trio odds via Harville
            trio_prob = harville_trio_prob(bp, rk[0], rk[1], rk[2])
            predicted_odds = (1.0 / trio_prob) * 0.75 if trio_prob > 0 else 9999  # 0.75 = takeout

            hit = frozenset(top) == t3s
            pay = B * market_odds if hit else 0
            results.append((predicted_odds, market_odds, hit, pay))
        cache[(alpha, ty)] = results
    print(f"  alpha={alpha:.2f} done", flush=True)

out = open(r'C:\Users\moribro2201\Desktop\predicted_odds_filter_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s + '\n')

# === Test A: Predicted odds filter only ===
p('=' * 120)
p('=== Test A: Predicted Odds Filter (Harville model estimate) x alpha ===')
p('  predicted_odds = (1/trio_prob) * 0.75 (takeout adjusted)')
p('=' * 120)
p()
h = f'{"alpha":>6}'
for mo in PRED_ODDS_LIMITS:
    ml = f'P<={mo}' if mo < 9999 else 'ALL'
    h += f'  {ml:>12}'
p(h)
p('-' * (8 + 14 * len(PRED_ODDS_LIMITS)))
for alpha in ALPHAS:
    line = f'{alpha:>5.2f} '
    for max_po in PRED_ODDS_LIMITS:
        tb = 0; tr = 0; rc = 0
        for ty in TY:
            for po, mo, hit, pay in cache[(alpha, ty)]:
                if po > max_po: continue
                tb += B; rc += 1; tr += pay
        rr = tr/tb*100 if tb > 0 else 0
        line += f'  {rr:>5.1f}%({rc:>4})'
    p(line)

# === Test B: Predicted odds filter - yearly breakdown ===
p()
p('=== Test B: Predicted Odds Filter - yearly breakdown ===')
p()
for alpha, max_po in [(0.0,10),(0.0,7),(0.15,10),(0.15,7),(0.30,10),(0.30,7),(0.50,10),(0.50,7),(0.50,5),(0.70,10),(0.70,7)]:
    parts = []
    tb_all = 0; tr_all = 0; rc_all = 0
    for ty in TY:
        tb = 0; tr = 0; rc = 0
        for po, mo, hit, pay in cache[(alpha, ty)]:
            if po > max_po: continue
            tb += B; rc += 1; tr += pay
        rr = tr/tb*100 if tb > 0 else 0
        parts.append(f'{ty}={rr:>5.1f}%({rc:>4}R)')
        tb_all += tb; tr_all += tr; rc_all += rc
    trr = tr_all/tb_all*100 if tb_all > 0 else 0
    p(f'  a={alpha:.2f} PredO<={max_po:<4} total={trr:>5.1f}% {rc_all:>5}R | {" ".join(parts)}')

# === Test C: Predicted odds vs Market odds filter comparison ===
p()
p('=' * 120)
p('=== Test C: Predicted Odds vs Market Odds Filter (alpha=0.50) ===')
p('=' * 120)
p()
p(f'  {"Filter":>20} {"Total RR":>8} {"R count":>7} | {"2021":>10} {"2022":>10} {"2023":>10} {"2024":>10} {"2025":>10} {"2026":>10}')
p(f'  {"-"*110}')

alpha = 0.50
for label, use_pred, max_val in [
    ('Pred<=5', True, 5), ('Pred<=7', True, 7), ('Pred<=10', True, 10), ('Pred<=15', True, 15), ('Pred<=20', True, 20),
    ('Market<=5', False, 5), ('Market<=7', False, 7), ('Market<=10', False, 10), ('Market<=15', False, 15), ('Market<=20', False, 20),
    ('ALL', False, 9999),
]:
    parts = []
    tb_all = 0; tr_all = 0; rc_all = 0
    for ty in TY:
        tb = 0; tr = 0; rc = 0
        for po, mo, hit, pay in cache[(alpha, ty)]:
            if use_pred and po > max_val: continue
            if not use_pred and mo > max_val: continue
            tb += B; rc += 1; tr += pay
        rr = tr/tb*100 if tb > 0 else 0
        parts.append(f'{rr:>5.1f}%({rc:>3}R)')
        tb_all += tb; tr_all += tr; rc_all += rc
    trr = tr_all/tb_all*100 if tb_all > 0 else 0
    p(f'  {label:>20} {trr:>7.1f}% {rc_all:>7} | {" ".join(parts)}')

# === Test D: Combined filter (Predicted + Market) ===
p()
p('=' * 120)
p('=== Test D: Combined Filters (alpha=0.50) ===')
p('=' * 120)
p()
p(f'  {"Filter":>25} {"Total RR":>8} {"R count":>7} | {"2021":>10} {"2022":>10} {"2023":>10} {"2024":>10} {"2025":>10} {"2026":>10}')
p(f'  {"-"*115}')

alpha = 0.50
combos = [
    ('Pred<=7 only', 7, 9999),
    ('Market<=10 only', 9999, 10),
    ('Pred<=7 & Market<=10', 7, 10),
    ('Pred<=10 only', 10, 9999),
    ('Market<=15 only', 9999, 15),
    ('Pred<=10 & Market<=15', 10, 15),
    ('Pred<=10 & Market<=10', 10, 10),
    ('Pred<=5 only', 5, 9999),
    ('Pred<=5 & Market<=10', 5, 10),
    ('ALL', 9999, 9999),
]
for label, max_pred, max_mkt in combos:
    parts = []
    tb_all = 0; tr_all = 0; rc_all = 0
    for ty in TY:
        tb = 0; tr = 0; rc = 0
        for po, mo, hit, pay in cache[(alpha, ty)]:
            if po > max_pred: continue
            if mo > max_mkt: continue
            tb += B; rc += 1; tr += pay
        rr = tr/tb*100 if tb > 0 else 0
        parts.append(f'{rr:>5.1f}%({rc:>3}R)')
        tb_all += tb; tr_all += tr; rc_all += rc
    trr = tr_all/tb_all*100 if tb_all > 0 else 0
    p(f'  {label:>25} {trr:>7.1f}% {rc_all:>7} | {" ".join(parts)}')

# === Test E: Predicted odds filter with varying alpha ===
p()
p('=' * 120)
p('=== Test E: Predicted Odds <= 10 with varying alpha (yearly) ===')
p('=' * 120)
p()
p(f'  {"alpha":>6} {"Total":>7} | {"2021":>12} {"2022":>12} {"2023":>12} {"2024":>12} {"2025":>12} {"2026":>12}')
p(f'  {"-"*100}')
for alpha in ALPHAS:
    parts = []
    tb_all = 0; tr_all = 0
    for ty in TY:
        tb = 0; tr = 0; rc = 0
        for po, mo, hit, pay in cache[(alpha, ty)]:
            if po > 10: continue
            tb += B; rc += 1; tr += pay
        rr = tr/tb*100 if tb > 0 else 0
        parts.append(f'{rr:>5.1f}%({rc:>4}R)')
        tb_all += tb; tr_all += tr
    trr = tr_all/tb_all*100 if tb_all > 0 else 0
    p(f'  {alpha:>5.2f} {trr:>6.1f}% | {" ".join(parts)}')

out.close()
print(f"\nDone! Results: C:\\Users\\moribro2201\\Desktop\\predicted_odds_filter_results.txt", flush=True)
