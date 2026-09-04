"""
v16: 年別シミュレーション（2020-2026）
学習: テスト年より前の全データ（ウォークフォワード）
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v16.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
BETA=1.03; SCALE=0.15; BUDGET=10000

def softmax(sc):
    s=[(x-50)*SCALE for x in sc]; mx=max(s) if s else 0
    e=[math.exp(x-mx) for x in s]; t=sum(e)
    return [x/t for x in e] if t>0 else []
def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p_**BETA for p_ in raw]; ps=sum(pw)
    return [p_/ps for p_ in pw]
def blendf(m,mk,alpha):
    bl=[math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p_/s for p_ in bl] if s>0 else bl

# 全レース+エントリー取得
races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

p(f'=== v16: 年別シミュレーション ===')
p(f'全レース: {len(races):,}')

test_years = [2020,2021,2022,2023,2024,2025,2026]
alphas = [0.10, 0.15, 0.20]

for alpha in alphas:
    p(f'\n{"="*90}')
    p(f'=== alpha={alpha:.2f} ===')
    p(f'{"="*90}')

    # 累積データリセット
    jc = defaultdict(lambda:{'r':0,'w':0})
    hr = defaultdict(list)

    # 2019年で初期化
    for rid,rd,vc,sf,dt in races:
        if rd >= '2020-01-01':
            continue  # continueで全レースを見る（breakだとスキップされる）
        if rd < '2019-01-01':
            continue
        res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
        for hn,fp,hid in res:
            ent = entry_cache.get(rid,{}).get(hn,{})
            jn = ent.get('jockey','')
            if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
            if hid:
                hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
                if len(hr[hid])>20: hr[hid]=hr[hid][-20:]

    p(f'Init(2019): {len(jc)} jockeys, {len(hr)} horses')

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

    yearly = []
    cum_b=0; cum_r=0

    for test_year in test_years:
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
            om = {int(r[0]):r[1] for r in oz}
            hl = sorted(om.keys())
            if len(hl)<5: continue
            early = [om[h] for h in hl]

            sc = [score(h,rid,vc,sf,dt) for h in hl]
            mp = softmax(sc); mkp = mktp(early); bp = blendf(mp,mkp,alpha)
            rk = sorted(range(len(hl)),key=lambda i:-bp[i])
            top = [hl[r] for r in rk[:3]]

            combo = '-'.join(str(h) for h in sorted(top))
            orow = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
            if not orow or orow[0]<=0: continue
            odds = orow[0]; hit = set(top)==set(t3[:3])
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
        cum_b += tb; cum_r += tr
        yearly.append({'year':test_year,'rr':rr,'tb':tb,'tr':tr,'profit':tr-tb,'races':traces,'hits':thits})

    p(f'\n{"年":<6} {"R数":>6} {"的中":>5} {"的中率":>6} {"投資":>14} {"収支":>14} {"回収率":>7}')
    p('-'*70)
    for r in yearly:
        hr_ = r['hits']/r['races']*100 if r['races']>0 else 0
        p(f'{r["year"]:<6} {r["races"]:>6} {r["hits"]:>5} {hr_:>5.1f}% {r["tb"]:>13,.0f}円 {r["profit"]:>+13,.0f}円 {r["rr"]:>6.1f}%')
    cum_rr = cum_r/cum_b*100 if cum_b>0 else 0
    tot_h = sum(r['hits'] for r in yearly)
    tot_r = sum(r['races'] for r in yearly)
    p(f'{"通算":<6} {tot_r:>6} {tot_h:>5} {tot_h/tot_r*100 if tot_r>0 else 0:>5.1f}% {cum_b:>13,.0f}円 {cum_r-cum_b:>+13,.0f}円 {cum_rr:>6.1f}%')

db.close(); out.close()
