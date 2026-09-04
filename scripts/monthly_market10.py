"""Market<=10 + alpha=0.50 monthly breakdown"""
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
        month = rdt[5:7]
        rl.append((hl, sc, early, om, t3s, trio, month))
    rd[ty] = rl
db.close()

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

alpha = 0.50; beta = 1.03; scale = 0.15; max_odds = 10

monthly = {}
for ty in TY:
    for hl, sc, early, om, t3s, trio, month in rd[ty]:
        n = len(hl)
        mp = softmax(sc, scale); mkp = mktp(early, beta)
        bp = blendf(mp, mkp, alpha)
        rk = sorted(range(n), key=lambda i: -bp[i])
        top = sorted([hl[rk[0]], hl[rk[1]], hl[rk[2]]])
        combo = f'{top[0]}-{top[1]}-{top[2]}'
        ov = trio.get(combo, 0)
        if ov <= 0 or ov > max_odds: continue
        hit = frozenset(top) == t3s
        pay = B * ov if hit else 0
        key = (ty, month)
        if key not in monthly: monthly[key] = {'b':0,'r':0,'h':0,'c':0}
        monthly[key]['b'] += B; monthly[key]['r'] += pay; monthly[key]['c'] += 1
        if hit: monthly[key]['h'] += 1

months = ['01','02','03','04','05','06','07','08','09','10','11','12']

print('=== Market<=10 + alpha=0.50 : Monthly RR (hits/races) ===')
print()
header = '  Month'
for ty in TY: header += f'     {ty}'
header += '    AllYears'
print(header)
print('  ' + '-' * 110)

for m in months:
    line = f'  {m}    '
    m_all_b = 0; m_all_r = 0
    for ty in TY:
        d = monthly.get((ty, m), {'b':0,'r':0,'h':0,'c':0})
        if d['b'] > 0:
            rr = d['r']/d['b']*100
            m_all_b += d['b']; m_all_r += d['r']
            line += f' {rr:>4.0f}%({d["h"]}/{d["c"]:>2})'
        else:
            line += f'     {"---":>8}'
    if m_all_b > 0:
        m_all_rr = m_all_r/m_all_b*100
        line += f'   {m_all_rr:>5.1f}%'
    print(line)

# Yearly totals
print('  ' + '-' * 110)
line = '  Total '
total_b = 0; total_r = 0
for ty in TY:
    tb = sum(monthly.get((ty,m),{'b':0})['b'] for m in months)
    tr = sum(monthly.get((ty,m),{'r':0})['r'] for m in months)
    hits = sum(monthly.get((ty,m),{'h':0})['h'] for m in months)
    rc = sum(monthly.get((ty,m),{'c':0})['c'] for m in months)
    total_b += tb; total_r += tr
    if tb > 0:
        rr = tr/tb*100
        line += f' {rr:>4.0f}%({hits}/{rc:>2})'
    else:
        line += f'     {"---":>8}'
total_rr = total_r/total_b*100 if total_b > 0 else 0
line += f'   {total_rr:>5.1f}%'
print(line)

# Cumulative P&L per year
print()
print('=== Cumulative P&L (yen) by month ===')
print()
header = '  Month'
for ty in TY: header += f'       {ty}'
header += '       Total'
print(header)
print('  ' + '-' * 100)

cum = {ty: 0 for ty in TY}
cum_total = 0
for m in months:
    line = f'  {m}    '
    m_pnl = 0
    for ty in TY:
        d = monthly.get((ty, m), {'b':0,'r':0})
        pnl = d['r'] - d['b']
        cum[ty] += pnl
        m_pnl += pnl
        line += f' {cum[ty]:>+10,}'
    cum_total += m_pnl
    line += f' {cum_total:>+10,}'
    print(line)

# Monthly average stats
print()
print('=== Monthly Average (all years combined) ===')
print()
print(f'  Month   AvgRR   Races  Hits  HitRate  AvgPayOdds')
print(f'  ' + '-' * 55)
for m in months:
    tb = 0; tr = 0; hits = 0; rc = 0
    for ty in TY:
        d = monthly.get((ty, m), {'b':0,'r':0,'h':0,'c':0})
        tb += d['b']; tr += d['r']; hits += d['h']; rc += d['c']
    if tb > 0:
        rr = tr/tb*100
        hr_ = hits/rc*100 if rc > 0 else 0
        avg_pay = tr/(hits*B) if hits > 0 else 0
        print(f'  {m}      {rr:>5.1f}%  {rc:>5}  {hits:>4}  {hr_:>5.1f}%    {avg_pay:>5.1f}x')
