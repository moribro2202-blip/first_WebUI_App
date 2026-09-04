"""
Test 1: Model Top3 only (no agree filter) + odds limit x alpha
Test 2: Agree filter + odds limit x alpha (comparison)
Test 3: Adaptive alpha (use prev year's best alpha for next year)
"""
import sqlite3, math
from collections import defaultdict

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
        mkt3 = set(sorted(hl, key=lambda h: om[h])[:3])
        rl.append((hl, sc, early, om, t3s, trio, mkt3))
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

ALPHAS = [0.0, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
MO = [5, 7, 10, 15, 20, 30, 9999]
beta = 1.03; scale = 0.15

# Pre-cache all per-race results for each alpha
cache = {}
for alpha in ALPHAS:
    for ty in TY:
        results = []
        for hl, sc, early, om, t3s, trio, mkt3 in rd[ty]:
            n = len(hl)
            mp = softmax(sc, scale); mkp = mktp(early, beta)
            if alpha <= 0.001: bp = mkp
            elif alpha >= 0.999: bp = mp
            else: bp = blendf(mp, mkp, alpha)
            rk = sorted(range(n), key=lambda i: -bp[i])
            top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
            combo = f'{top[0]}-{top[1]}-{top[2]}'
            ov = trio.get(combo, 0)
            if ov <= 0: continue
            agree = set(top) == mkt3
            hit = frozenset(top) == t3s
            pay = B * ov if hit else 0
            results.append((agree, ov, hit, pay))
        cache[(alpha, ty)] = results
print("Cache built.", flush=True)

def calc(alpha, ty, filter_agree, max_odds):
    tb = 0; tr = 0; hits = 0; rc = 0
    for agree, ov, hit, pay in cache[(alpha, ty)]:
        if filter_agree and not agree: continue
        if ov > max_odds: continue
        tb += B; rc += 1; tr += pay
        if hit: hits += 1
    return tb, tr, hits, rc

out = open(r'C:\Users\moribro2201\Desktop\filter_adaptive_results.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s + '\n')

# === Test 1: No agree filter ===
p('=' * 110)
p('=== Test 1: Model Top3 ONLY (no agree filter) + odds limit x alpha ===')
p('=' * 110)
p()
h = f'{"alpha":>6}'
for mo in MO:
    ml = f'<={mo}' if mo < 9999 else 'ALL'
    h += f'  {ml:>12}'
p(h)
p('-' * (8 + 14 * len(MO)))
for alpha in ALPHAS:
    line = f'{alpha:>5.2f} '
    for max_odds in MO:
        tb = 0; tr = 0; rc = 0
        for ty in TY:
            b, r, _, c = calc(alpha, ty, False, max_odds)
            tb += b; tr += r; rc += c
        rr = tr/tb*100 if tb > 0 else 0
        line += f'  {rr:>5.1f}%({rc:>4})'
    p(line)

p()
p('=== Test 1b: No agree filter - yearly breakdown ===')
p()
for alpha, max_odds in [(0.0,10),(0.15,10),(0.30,10),(0.50,10),(0.50,7),(0.50,5),(0.70,10),(0.70,7)]:
    parts = []
    tb_all = 0; tr_all = 0; rc_all = 0
    for ty in TY:
        b, r, _, c = calc(alpha, ty, False, max_odds)
        rr = r/b*100 if b > 0 else 0
        parts.append(f'{ty}={rr:>5.1f}%({c:>4}R)')
        tb_all += b; tr_all += r; rc_all += c
    trr = tr_all/tb_all*100 if tb_all > 0 else 0
    ml = f'<={max_odds}' if max_odds < 9999 else 'ALL'
    p(f'  a={alpha:.2f} MxO={ml:<4} total={trr:>5.1f}% {rc_all:>5}R | {" ".join(parts)}')

# === Test 2: Agree filter (comparison) ===
p()
p('=' * 110)
p('=== Test 2: Agree filter + odds limit x alpha (comparison) ===')
p('=' * 110)
p()
h = f'{"alpha":>6}'
for mo in MO:
    ml = f'<={mo}' if mo < 9999 else 'ALL'
    h += f'  {ml:>12}'
p(h)
p('-' * (8 + 14 * len(MO)))
for alpha in ALPHAS:
    line = f'{alpha:>5.2f} '
    for max_odds in MO:
        tb = 0; tr = 0; rc = 0
        for ty in TY:
            b, r, _, c = calc(alpha, ty, True, max_odds)
            tb += b; tr += r; rc += c
        rr = tr/tb*100 if tb > 0 else 0
        line += f'  {rr:>5.1f}%({rc:>4})'
    p(line)

p()
p('=== Test 2b: Agree filter - yearly breakdown ===')
p()
for alpha, max_odds in [(0.0,10),(0.15,10),(0.30,10),(0.50,10),(0.50,7),(0.50,5),(0.70,10),(0.70,7)]:
    parts = []
    tb_all = 0; tr_all = 0; rc_all = 0
    for ty in TY:
        b, r, _, c = calc(alpha, ty, True, max_odds)
        rr = r/b*100 if b > 0 else 0
        parts.append(f'{ty}={rr:>5.1f}%({c:>4}R)')
        tb_all += b; tr_all += r; rc_all += c
    trr = tr_all/tb_all*100 if tb_all > 0 else 0
    ml = f'<={max_odds}' if max_odds < 9999 else 'ALL'
    p(f'  a={alpha:.2f} MxO={ml:<4} total={trr:>5.1f}% {rc_all:>5}R | {" ".join(parts)}')

# === Test 3: Adaptive Alpha ===
p()
p('=' * 110)
p('=== Test 3: Adaptive Alpha (prev year best -> next year) ===')
p('=' * 110)
p()

for max_odds_val in [7, 10, 15]:
    for use_agree in [True, False]:
        flabel = 'agree' if use_agree else 'all'
        ml = f'<={max_odds_val}'

        # Find best alpha for each year
        best_alpha = {}
        for ty in TY:
            best_rr = -1; best_a = 0
            for alpha in ALPHAS:
                b, r, _, c = calc(alpha, ty, use_agree, max_odds_val)
                rr = r/b*100 if b > 0 else 0
                if rr > best_rr: best_rr = rr; best_a = alpha
            best_alpha[ty] = (best_a, best_rr)

        p(f'--- MxO{ml} filter={flabel} ---')
        p(f'  {"Year":>4}  {"BestA":>5} {"OracleRR":>8}  {"AdaptA":>6} {"AdaptRR":>8}  {"Fix.15":>8}  {"Fix.30":>8}  {"Fix.50":>8}')
        p(f'  {"-"*75}')

        totals = {'oracle':[0,0], 'adapt':[0,0], 'f15':[0,0], 'f30':[0,0], 'f50':[0,0]}

        for i, ty in enumerate(TY):
            ba, oracle_rr = best_alpha[ty]
            b_o, r_o, _, _ = calc(ba, ty, use_agree, max_odds_val)
            totals['oracle'][0] += b_o; totals['oracle'][1] += r_o

            # Adaptive: prev year's best
            if i == 0:
                ada = 0.30  # reasonable default
            else:
                ada = best_alpha[TY[i-1]][0]
            b_a, r_a, _, _ = calc(ada, ty, use_agree, max_odds_val)
            adapt_rr = r_a/b_a*100 if b_a > 0 else 0
            totals['adapt'][0] += b_a; totals['adapt'][1] += r_a

            for key, a_val in [('f15', 0.15), ('f30', 0.30), ('f50', 0.50)]:
                b_f, r_f, _, _ = calc(a_val, ty, use_agree, max_odds_val)
                totals[key][0] += b_f; totals[key][1] += r_f
                if key == 'f15': f15_rr = r_f/b_f*100 if b_f > 0 else 0
                if key == 'f30': f30_rr = r_f/b_f*100 if b_f > 0 else 0
                if key == 'f50': f50_rr = r_f/b_f*100 if b_f > 0 else 0

            p(f'  {ty:>4}  a={ba:.2f} {oracle_rr:>7.1f}%  a={ada:.2f}  {adapt_rr:>7.1f}%  {f15_rr:>7.1f}%  {f30_rr:>7.1f}%  {f50_rr:>7.1f}%')

        p(f'  {"Total":>4}  {"":>5} {totals["oracle"][1]/totals["oracle"][0]*100:>7.1f}%  {"":>6} {totals["adapt"][1]/totals["adapt"][0]*100:>7.1f}%  {totals["f15"][1]/totals["f15"][0]*100:>7.1f}%  {totals["f30"][1]/totals["f30"][0]*100:>7.1f}%  {totals["f50"][1]/totals["f50"][0]*100:>7.1f}%')
        p()

out.close()
print("Done! Results: C:\\Users\\moribro2201\\Desktop\\filter_adaptive_results.txt", flush=True)
