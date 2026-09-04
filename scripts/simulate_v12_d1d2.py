"""
v12: D1(レースタイプ別分析) + D2(市場乖離選別)
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v12.txt', 'w', encoding='utf-8')
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

# === D1: レースタイプ別分析 ===
p('='*100)
p('=== D1: レースタイプ別の回収率分析 ===')
p('='*100)

categories = defaultdict(lambda:{'b':0,'r':0,'h':0,'c':0})

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
    # 市場top3
    mkt_top=sorted(hl,key=lambda h:om[h])[:3]

    combo='-'.join(str(h) for h in sorted(top))
    orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
    if not orow or orow[0]<=0: continue
    odds=orow[0]; hit=set(top)==set(t3[:3])

    # カテゴリ分類
    # 馬場
    categories[f'馬場:{sf}']['c']+=1; categories[f'馬場:{sf}']['b']+=BUDGET
    if hit: categories[f'馬場:{sf}']['h']+=1; categories[f'馬場:{sf}']['r']+=BUDGET*odds

    # 距離帯
    if dt<=1200: dcat='短距離(〜1200m)'
    elif dt<=1600: dcat='マイル(1201-1600m)'
    elif dt<=2000: dcat='中距離(1601-2000m)'
    elif dt<=2400: dcat='中長距離(2001-2400m)'
    else: dcat='長距離(2401m〜)'
    categories[f'距離:{dcat}']['c']+=1; categories[f'距離:{dcat}']['b']+=BUDGET
    if hit: categories[f'距離:{dcat}']['h']+=1; categories[f'距離:{dcat}']['r']+=BUDGET*odds

    # 頭数
    if len(hl)<=8: hcat='少頭数(〜8頭)'
    elif len(hl)<=12: hcat='中頭数(9-12頭)'
    elif len(hl)<=16: hcat='多頭数(13-16頭)'
    else: hcat='大多頭(17頭〜)'
    categories[f'頭数:{hcat}']['c']+=1; categories[f'頭数:{hcat}']['b']+=BUDGET
    if hit: categories[f'頭数:{hcat}']['h']+=1; categories[f'頭数:{hcat}']['r']+=BUDGET*odds

    # 競馬場
    vname={'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}.get(vc,vc)
    categories[f'場:{vname}']['c']+=1; categories[f'場:{vname}']['b']+=BUDGET
    if hit: categories[f'場:{vname}']['h']+=1; categories[f'場:{vname}']['r']+=BUDGET*odds

    # D2: 市場乖離度
    model_set=set(top); market_set=set(mkt_top)
    diff_count=len(model_set-market_set)
    categories[f'乖離:{diff_count}頭異なる']['c']+=1; categories[f'乖離:{diff_count}頭異なる']['b']+=BUDGET
    if hit: categories[f'乖離:{diff_count}頭異なる']['h']+=1; categories[f'乖離:{diff_count}頭異なる']['r']+=BUDGET*odds

# 出力
for prefix in ['馬場','距離','頭数','場','乖離']:
    p(f'\n--- {prefix}別 ---')
    p(f'{"カテゴリ":<30} {"R数":>5} {"的中":>4} {"的中率":>6} {"投資":>12} {"払戻":>12} {"回収率":>7}')
    p('-'*80)
    items=[(k,v) for k,v in categories.items() if k.startswith(prefix)]
    for k,v in sorted(items, key=lambda x:-x[1]['r']/x[1]['b']*100 if x[1]['b']>0 else 0):
        rr=v['r']/v['b']*100 if v['b']>0 else 0
        hr_=v['h']/v['c']*100 if v['c']>0 else 0
        p(f'{k:<30} {v["c"]:>5} {v["h"]:>4} {hr_:>5.1f}% {v["b"]:>11,.0f}円 {v["r"]:>11,.0f}円 {rr:>6.1f}%')

# === D2: 市場乖離フィルタのシミュレーション ===
p(f'\n{"="*100}')
p('=== D2: 市場乖離フィルタ ===')
p(f'{"="*100}')

filters = {
    'v7ベースライン(全レース)': lambda diff: True,
    'D2-a: 1頭以上異なる': lambda diff: diff >= 1,
    'D2-b: 2頭以上異なる': lambda diff: diff >= 2,
    'D2-c: 3頭異なる(完全不一致)': lambda diff: diff >= 3,
    'D2-d: 0頭異なる(完全一致のみ)': lambda diff: diff == 0,
    'D2-e: 1頭だけ異なる': lambda diff: diff == 1,
}

filter_results = []

for fname, ffn in filters.items():
    tb=0;tr=0;traces=0;thits=0
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
        sc=[score(h,rid,vc,sf,dt) for h in hl]
        mp=softmax(sc); mkp=mktp(early); bp=blendf(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        top=[hl[r] for r in rk[:3]]
        mkt_top=sorted(hl,key=lambda h:om[h])[:3]
        diff=len(set(top)-set(mkt_top))

        if not ffn(diff): continue

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue
        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=BUDGET;traces+=1
        month=rd[:7]; mo[month]['b']+=BUDGET; mo[month]['n']+=1
        if hit: tr+=BUDGET*odds; thits+=1; mo[month]['r']+=BUDGET*odds

    rr=tr/tb*100 if tb>0 else 0
    filter_results.append({'name':fname,'rr':rr,'tb':tb,'tr':tr,'profit':tr-tb,'races':traces,'hits':thits,'mo':dict(mo)})

p(f'\n{"#":>3} {"フィルタ":<35} {"R数":>5} {"的中":>4} {"的中率":>6} {"収支":>13} {"回収率":>7}')
p('-'*80)
for i,r in enumerate(sorted(filter_results,key=lambda x:-x['rr'])):
    hr_=r['hits']/r['races']*100 if r['races']>0 else 0
    p(f'{i+1:>3} {r["name"]:<35} {r["races"]:>5} {r["hits"]:>4} {hr_:>5.1f}% {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

# ベストの月別
best=max(filter_results,key=lambda x:x['rr'])
p(f'\n--- ベスト: {best["name"]} ---')
cb=0;cr=0
for m in sorted(best['mo'].keys()):
    d=best['mo'][m]; cb+=d['b'];cr+=d['r']
    p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

# === 最強の組み合わせ: D1ベストカテゴリ + D2ベストフィルタ ===
p(f'\n{"="*100}')
p('=== D1+D2 組み合わせフィルタ ===')
p(f'{"="*100}')

# D1で回収率が高いカテゴリを特定して、それだけに賭ける
combo_filters = {
    'D1: 芝のみ': lambda sf,dt,hl,diff: sf=='芝',
    'D1: ダートのみ': lambda sf,dt,hl,diff: sf!='芝',
    'D1: 中距離(1601-2000)': lambda sf,dt,hl,diff: 1601<=dt<=2000,
    'D1: 短距離(〜1200)': lambda sf,dt,hl,diff: dt<=1200,
    'D1: マイル(1201-1600)': lambda sf,dt,hl,diff: 1201<=dt<=1600,
    'D1: 多頭数(13+)': lambda sf,dt,hl,diff: len(hl)>=13,
    'D1+D2: 芝+1頭以上乖離': lambda sf,dt,hl,diff: sf=='芝' and diff>=1,
    'D1+D2: 中距離+1頭以上': lambda sf,dt,hl,diff: 1601<=dt<=2000 and diff>=1,
    'D1+D2: 多頭数+1頭以上': lambda sf,dt,hl,diff: len(hl)>=13 and diff>=1,
}

combo_results = []
for cname, cfn in combo_filters.items():
    tb=0;tr=0;traces=0;thits=0
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
        mkt_top=sorted(hl,key=lambda h:om[h])[:3]
        diff=len(set(top)-set(mkt_top))

        if not cfn(sf,dt,hl,diff): continue

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue
        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=BUDGET;traces+=1
        if hit: tr+=BUDGET*odds; thits+=1

    rr=tr/tb*100 if tb>0 else 0
    combo_results.append({'name':cname,'rr':rr,'races':traces,'hits':thits,'profit':tr-tb})

p(f'\n{"#":>3} {"フィルタ":<35} {"R数":>5} {"的中":>4} {"収支":>13} {"回収率":>7}')
p('-'*75)
for i,r in enumerate(sorted(combo_results,key=lambda x:-x['rr'])):
    p(f'{i+1:>3} {r["name"]:<35} {r["races"]:>5} {r["hits"]:>4} {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

db.close(); out.close()
