"""
v14: 馬体重±10kg以上の馬の扱い
A: その馬のスコアを大幅減点
B: その馬を上位3頭候補から除外（4番手が繰り上がる）
C: その馬が上位3頭に含まれるレースごと除外
"""
import sqlite3, math, sys, os
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v14.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
BETA=1.03; ALPHA=0.15; SCALE=0.15; BUDGET=10000

def softmax(sc):
    s=[(x-50)*SCALE for x in sc]; mx=max(s) if s else 0
    e=[math.exp(x-mx) for x in s]; t=sum(e)
    return [x/t for x in e] if t>0 else []
def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p_**BETA for p_ in raw]; ps=sum(pw)
    return [p_/ps for p_ in pw]
def blendf(m,mk):
    bl=[math.exp(ALPHA*math.log(max(a,1e-10))+(1-ALPHA)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p_/s for p_ in bl] if s>0 else bl

races=db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache={}
for rid,_,_,_,_ in races:
    es=db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid]={e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

# TYB馬体重ロード
tyb_weight = {}
tyb_dir = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb\TYB'
for fname in sorted(os.listdir(tyb_dir)):
    if not fname.endswith('.txt'): continue
    buf = open(os.path.join(tyb_dir, fname), 'rb').read()
    for l in buf.split(b'\r\n'):
        if len(l) < 92: continue
        try:
            rid_key = l[0:8].decode()
            hn = int(l[8:10].decode())
            wt = int(l[88:91].decode(errors='replace').strip() or '0')
            diff_str = l[91:95].decode(errors='replace').replace(' ','')
            diff = int(diff_str) if diff_str else 0
            if wt > 300:
                if rid_key not in tyb_weight: tyb_weight[rid_key] = {}
                tyb_weight[rid_key][hn] = (wt, diff)
        except: pass

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

def base_score(h,rid,vc,sf,dt):
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

def get_weight_diff(rid, hn):
    tw = tyb_weight.get(rid, {}).get(hn)
    return tw[1] if tw else None

p('=== v14: 馬体重±10kg以上の扱い ===\n')

strategies = {}

# ベースライン
strategies['v7ベースライン'] = ('normal', 0, False)

# A: スコア減点
for penalty in [5, 10, 15, 20, 30]:
    strategies[f'A: 減点-{penalty}'] = ('penalty', penalty, False)

# B: 候補から除外（次の馬が繰り上がり）
strategies['B: 候補除外'] = ('exclude', 0, False)

# C: レースごと除外
strategies['C: レース除外'] = ('skip_race', 0, False)

# 閾値違い
for th in [8, 12, 15, 20]:
    strategies[f'B: 除外(閾値±{th}kg)'] = ('exclude', th, False)

# 組み合わせ: B + 乖離フィルタ
strategies['B除外+乖離フィルタ'] = ('exclude', 0, True)

all_results = []

for sname, (mode, param, use_d2) in strategies.items():
    threshold = param if mode in ('exclude',) and param > 0 else 10
    if mode == 'penalty': threshold = 10

    tb=0;tr=0;traces=0;thits=0;skipped=0
    mo=defaultdict(lambda:{'b':0,'r':0,'n':0})

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

        sc=[base_score(h,rid,vc,sf,dt) for h in hl]

        # 馬体重処理
        heavy_horses = set()
        for i, h in enumerate(hl):
            wd = get_weight_diff(rid, h)
            if wd is not None and abs(wd) >= threshold:
                heavy_horses.add(h)
                if mode == 'penalty':
                    sc[i] -= param

        mp=softmax(sc); mkp=mktp(early); bp=blendf(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])

        if mode == 'exclude' or mode == 'skip_race':
            # 上位候補から体重変動馬を除外
            top = []
            for r_idx in rk:
                h = hl[r_idx]
                if mode == 'exclude' and h in heavy_horses:
                    continue
                top.append(h)
                if len(top) >= 3: break

            if len(top) < 3: continue

            if mode == 'skip_race' and any(h in heavy_horses for h in [hl[rk[0]], hl[rk[1]], hl[rk[2]]]):
                skipped += 1; continue

        else:
            top = [hl[r] for r in rk[:3]]

        # D2フィルタ
        if use_d2:
            mkt_top = sorted(hl, key=lambda h: om[h])[:3]
            if set(top) == set(mkt_top): continue

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue
        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=BUDGET;traces+=1
        month=rd[:7]; mo[month]['b']+=BUDGET; mo[month]['n']+=1
        if hit: tr+=BUDGET*odds; thits+=1; mo[month]['r']+=BUDGET*odds

    rr=tr/tb*100 if tb>0 else 0
    all_results.append({'name':sname,'rr':rr,'tb':tb,'tr':tr,'profit':tr-tb,'races':traces,'hits':thits,'skipped':skipped,'mo':dict(mo)})

p(f'{"#":>3} {"戦略":<25} {"R数":>5} {"skip":>5} {"的中":>4} {"的中率":>6} {"収支":>13} {"回収率":>7}')
p('-'*80)
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])):
    hr_=r['hits']/r['races']*100 if r['races']>0 else 0
    p(f'{i+1:>3} {r["name"]:<25} {r["races"]:>5} {r["skipped"]:>5} {r["hits"]:>4} {hr_:>5.1f}% {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

# 上位3の月別
p(f'\n=== 上位3の月別 ===')
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])[:3]):
    p(f'\n--- {i+1}位: {r["name"]} (回収率{r["rr"]:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(r['mo'].keys()):
        d=r['mo'][m]; cb+=d['b'];cr+=d['r']
        p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

db.close(); out.close()
