"""
v16b: 年別シミュレーション（単勝◎+馬連◎○+三連複◎○▲）
2019-2023はOZの単勝・馬連のみ、2024以降は三連複も
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v16b.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
BETA=1.03; SCALE=0.15; BUDGET=10000; ALPHA=0.15

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

races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

jc = defaultdict(lambda:{'r':0,'w':0}); hr = defaultdict(list)

# 2019年で初期化
for rid,rd,vc,sf,dt in races:
    if rd >= '2020-01-01': continue
    res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
    for hn,fp,hid in res:
        ent = entry_cache.get(rid,{}).get(hn,{})
        jn = ent.get('jockey','')
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

p(f'=== v16b: 年別シミュレーション（全券種対応） ===\n')

bet_types = ['単勝◎','馬連◎○','三連複◎○▲']

for bt_name in bet_types:
    p(f'\n{"="*80}')
    p(f'=== {bt_name} ===')
    p(f'{"="*80}')

    # alphaごとにリセットが必要なので、累積をコピー
    jc2 = defaultdict(lambda:{'r':0,'w':0})
    hr2 = defaultdict(list)
    for k,v in jc.items(): jc2[k] = dict(v)
    for k,v in hr.items(): hr2[k] = list(v)

    # jc, hrをjc2, hr2に置き換え（グローバル参照を避ける）
    _jc_bak = jc; _hr_bak = hr

    yearly = []
    for test_year in range(2020, 2027):
        ys = f'{test_year}-01-01'
        ye = f'{test_year+1}-01-01'
        tb=0;tr=0;traces=0;thits=0

        for rid,rd,vc,sf,dt in races:
            if rd < ys or rd >= ye: continue
            res = db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
            if len(res)<5: continue
            t3 = [r[0] for r in res if r[1]<=3]
            if len(t3)<3: continue
            oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
            if not oz: continue
            om = {int(r[0]):r[1] for r in oz}; hl = sorted(om.keys())
            if len(hl)<5: continue
            early = [om[h] for h in hl]

            sc = [score(h,rid,vc,sf,dt) for h in hl]
            mp = softmax(sc); mkp = mktp(early); bp = blendf(mp,mkp)
            rk = sorted(range(len(hl)),key=lambda i:-bp[i])
            top = [hl[r] for r in rk[:3]]

            if bt_name == '単勝◎':
                # 単勝1番手
                combo = str(top[0])
                db_bt = 'win'
                hit = top[0] == t3[0]
            elif bt_name == '馬連◎○':
                combo = '-'.join(str(h) for h in sorted(top[:2]))
                db_bt = 'umaren'
                hit = set(top[:2]) == set(t3[:2])
            else:
                combo = '-'.join(str(h) for h in sorted(top[:3]))
                db_bt = 'sanrenpuku'
                hit = set(top[:3]) == set(t3[:3])

            orow = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",(rid,db_bt,combo)).fetchone()
            if not orow or orow[0]<=0: continue
            odds = orow[0]
            tb += BUDGET; traces += 1
            if hit: tr += BUDGET*odds; thits += 1

        # 年のデータで累積更新
        for rid,rd,vc,sf,dt in races:
            if rd < ys or rd >= ye: continue
            res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
            for hn,fp,hid in res:
                ent = entry_cache.get(rid,{}).get(hn,{})
                jn = ent.get('jockey','')
                if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
                if hid:
                    hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
                    if len(hr[hid])>20: hr[hid]=hr[hid][-20:]

        rr = tr/tb*100 if tb>0 else 0
        yearly.append({'year':test_year,'rr':rr,'races':traces,'hits':thits,'profit':tr-tb,'tb':tb})

    p(f'\n{"年":<6} {"R数":>6} {"的中":>5} {"的中率":>6} {"投資":>13} {"収支":>13} {"回収率":>7}')
    p('-'*65)
    for r in yearly:
        hr_ = r['hits']/r['races']*100 if r['races']>0 else 0
        p(f'{r["year"]:<6} {r["races"]:>6} {r["hits"]:>5} {hr_:>5.1f}% {r["tb"]:>12,.0f}円 {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')
    tot_b = sum(r['tb'] for r in yearly)
    tot_r = sum(r['tb']+r['profit'] for r in yearly)
    tot_rr = tot_r/tot_b*100 if tot_b>0 else 0
    p(f'{"通算":<6} {sum(r["races"] for r in yearly):>6} {sum(r["hits"] for r in yearly):>5} {"":>6} {tot_b:>12,.0f}円 {tot_r-tot_b:>+12,.0f}円 {tot_rr:>6.1f}%')

    # jc, hrを元に戻す
    jc = _jc_bak; hr = _hr_bak

db.close(); out.close()
