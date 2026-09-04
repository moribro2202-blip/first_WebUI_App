"""
v9: モデル確信度による賭け金調整
上位3頭の確率が集中しているレースは多く賭け、拮抗しているレースは少なく賭ける
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v9.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
BETA=1.03; L2=0.8; L3=0.6; ALPHA=0.15; SCALE=0.15

def softmax(sc):
    s=[(x-50)*SCALE for x in sc]; mx=max(s) if s else 0
    e=[math.exp(x-mx) for x in s]; t=sum(e)
    return [x/t for x in e] if t>0 else []
def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p**BETA for p in raw]; ps=sum(pw)
    return [p/ps for p in pw]
def blendf(m,mk):
    bl=[math.exp(ALPHA*math.log(max(a,1e-10))+(1-ALPHA)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p/s for p in bl] if s>0 else bl

races=db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache={}
for rid,_,_,_,_ in races:
    es=db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid]={e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

jc=defaultdict(lambda:{'r':0,'w':0}); hr=defaultdict(list)
for rid,rd,vc,sf,dt in races:
    if rd>='2026-01-01': break
    res=db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
    for hn,fp,hid in res:
        ent=entry_cache.get(rid,{}).get(hn,{})
        jn=ent.get('jockey','')
        if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid])>20: hr[hid]=hr[hid][-20:]

def score(h,rid,vc,sf,dt):
    base=50.0; ent=entry_cache.get(rid,{}).get(h,{})
    hid=ent.get('hid',''); jn=ent.get('jockey','')
    jb=0
    if jn and jn in jc and jc[jn]['r']>=20: jb=(jc[jn]['w']/jc[jn]['r']-0.08)*50
    hb=db_=sb=vb=tb=0
    if hid and hid in hr:
        rc=hr[hid]
        if len(rc)>=2: hb=(6-sum(r['fp'] for r in rc[-5:])/len(rc[-5:]))*2
        dr=[r for r in rc if r['dist'] and abs(r['dist']-dt)<=200]
        if len(dr)>=2: db_=(6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:]))*1.5
        sr=[r for r in rc if r['surface']==sf]
        if len(sr)>=2: sb=(6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:]))*1.5
        vr=[r for r in rc if r['venue']==vc]
        if len(vr)>=2: vb=(6-sum(r['fp'] for r in vr[-5:])/len(vr[-5:]))*1.0
        if len(rc)>=3:
            l3=[r['fp'] for r in rc[-3:]]
            if l3[-1]<l3[0]: tb=(l3[0]-l3[-1])*0.8
    return base+jb+hb+db_+sb+vb+tb

p('=== v9: モデル確信度による賭け金調整 ===\n')

# 賭け金調整方式
# BASE_BUDGET = 平均予算。確信度に応じて増減。合計がBASE_BUDGET×レース数に近くなるように
strategies = {
    'v7固定10000円': lambda conf, avg: 10000,
    'C1-a: 線形(5000-15000)': lambda conf, avg: max(100, min(20000, int(round((5000 + (conf - 0.30) / 0.40 * 10000) / 100) * 100))),
    'C1-b: 線形(3000-20000)': lambda conf, avg: max(100, min(30000, int(round((3000 + (conf - 0.25) / 0.50 * 17000) / 100) * 100))),
    'C1-c: 2段階(低5000/高15000)': lambda conf, avg: 15000 if conf >= 0.50 else 5000,
    'C1-d: 3段階(3/10/20k)': lambda conf, avg: 20000 if conf >= 0.60 else (10000 if conf >= 0.45 else 3000),
    'C1-e: 確率比例': lambda conf, avg: max(100, int(round(conf * 25000 / 100) * 100)),
    'C1-f: 線形+skip<35%': lambda conf, avg: 0 if conf < 0.35 else max(100, min(20000, int(round((3000 + (conf - 0.35) / 0.40 * 17000) / 100) * 100))),
    'C1-g: 線形+skip<30%': lambda conf, avg: 0 if conf < 0.30 else max(100, min(20000, int(round((3000 + (conf - 0.30) / 0.45 * 17000) / 100) * 100))),
}

all_results = []

for sname, sizing_fn in strategies.items():
    tb=0;tr=0;traces=0;thits=0;skipped=0
    mo=defaultdict(lambda:{'b':0,'r':0,'n':0})
    conf_bins = defaultdict(lambda:{'b':0,'r':0,'h':0,'c':0})

    for rid,rd,vc,sf,dt in races:
        if rd<'2026-01-01': continue
        res=db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
        if len(res)<5: continue
        t3=[r[0] for r in res if r[1]<=3]
        if len(t3)<3: continue
        oz=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
        if not oz: continue
        om={int(r[0]):r[1] for r in oz}; hl=sorted(om.keys())
        if len(hl)<5: continue

        early=[om[h] for h in hl]
        sc=[score(h,rid,vc,sf,dt) for h in hl]
        mp=softmax(sc); mkp=mktp(early); bp=blendf(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        top=[hl[r] for r in rk[:3]]

        # 確信度 = 上位3頭の合計確率
        conf = sum(bp[rk[i]] for i in range(3))

        # 賭け金決定
        amount = sizing_fn(conf, 0)
        if amount <= 0:
            skipped += 1
            continue

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue

        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=amount; traces+=1
        month=rd[:7]; mo[month]['b']+=amount; mo[month]['n']+=1

        # 確信度帯別の集計
        if conf < 0.35: bin_key = '<35%'
        elif conf < 0.45: bin_key = '35-45%'
        elif conf < 0.55: bin_key = '45-55%'
        elif conf < 0.65: bin_key = '55-65%'
        else: bin_key = '65%+'
        conf_bins[bin_key]['c'] += 1
        conf_bins[bin_key]['b'] += amount

        if hit:
            ret = amount * odds
            tr += ret; thits += 1
            mo[month]['r'] += ret
            conf_bins[bin_key]['h'] += 1
            conf_bins[bin_key]['r'] += ret

    rr = tr/tb*100 if tb>0 else 0
    avg_bet = tb/traces if traces>0 else 0
    all_results.append({
        'name':sname,'rr':rr,'tb':tb,'tr':tr,'profit':tr-tb,
        'races':traces,'hits':thits,'skipped':skipped,'avg_bet':avg_bet,
        'mo':dict(mo),'conf_bins':dict(conf_bins),
    })

# ランキング
p(f'{"#":>3} {"戦略":<30} {"R数":>5} {"skip":>5} {"平均額":>7} {"的中":>4} {"投資":>13} {"収支":>13} {"回収率":>7}')
p('-'*100)
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])):
    p(f'{i+1:>3} {r["name"]:<30} {r["races"]:>5} {r["skipped"]:>5} {r["avg_bet"]:>6,.0f}円 {r["hits"]:>4} {r["tb"]:>12,.0f}円 {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

# 上位3の月別
p(f'\n=== 上位3の月別推移 ===')
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])[:3]):
    p(f'\n--- {i+1}位: {r["name"]} (回収率{r["rr"]:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(r['mo'].keys()):
        d=r['mo'][m]; cb+=d['b'];cr+=d['r']
        p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

# ベースラインの確信度帯別分析
p(f'\n=== 確信度帯別の成績（v7固定10000円） ===')
base = [r for r in all_results if r['name']=='v7固定10000円'][0]
p(f'{"帯":<10} {"R数":>5} {"的中":>4} {"的中率":>6} {"投資":>12} {"払戻":>12} {"回収率":>7}')
p('-'*60)
for k in ['<35%','35-45%','45-55%','55-65%','65%+']:
    b = base['conf_bins'].get(k, {'c':0,'h':0,'b':0,'r':0})
    if b['c']==0: continue
    p(f'{k:<10} {b["c"]:>5} {b["h"]:>4} {b["h"]/b["c"]*100:>5.1f}% {b["b"]:>11,.0f}円 {b["r"]:>11,.0f}円 {b["r"]/b["b"]*100 if b["b"]>0 else 0:>6.1f}%')

db.close(); out.close()
