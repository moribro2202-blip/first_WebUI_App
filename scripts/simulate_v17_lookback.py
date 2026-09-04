"""
v17: データ鮮度（ルックバック期間）の影響
各テスト年に対して、直近N年分のデータだけを使って予測
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v17.txt', 'w', encoding='utf-8')
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

p('=== v17: データ鮮度（ルックバック期間）の影響 ===\n')

lookbacks = [1, 2, 3, 5, 7]  # 直近N年
test_years = [2021, 2022, 2023, 2024, 2025, 2026]

all_results = []

for lb in lookbacks:
    p(f'\n--- ルックバック {lb}年 ---')

    yearly = []

    for test_year in test_years:
        # 学習データ: テスト年の直前N年分のみ
        train_start = f'{test_year - lb}-01-01'
        train_end = f'{test_year}-01-01'
        test_start = f'{test_year}-01-01'
        test_end = f'{test_year + 1}-01-01'

        # 累積データをリセット（毎テスト年でクリーンスタート）
        jc = defaultdict(lambda:{'r':0,'w':0})
        hr = defaultdict(list)

        # 学習データで初期化
        for rid,rd,vc,sf,dt in races:
            if rd < train_start or rd >= train_end: continue
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

        tb=0;tr=0;traces=0;thits=0

        for rid,rd,vc,sf,dt in races:
            if rd < test_start or rd >= test_end: continue
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

            combo = '-'.join(str(h) for h in sorted(top))
            orow = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
            if not orow or orow[0]<=0: continue
            odds = orow[0]; hit = set(top)==set(t3[:3])
            tb += BUDGET; traces += 1
            if hit: tr += BUDGET*odds; thits += 1

        rr = tr/tb*100 if tb>0 else 0
        yearly.append({'year':test_year,'rr':rr,'races':traces,'hits':thits,'profit':tr-tb})

    for r in yearly:
        hr_ = r['hits']/r['races']*100 if r['races']>0 else 0
        p(f'  {r["year"]}: {r["races"]:>5}R 的中{r["hits"]:>4} ({hr_:.1f}%) 回収{r["rr"]:.1f}% 収支{r["profit"]:+,.0f}円')

    # 通算
    tot_b = sum(r['races'] for r in yearly)*BUDGET
    tot_r = sum(r['races']*BUDGET + r['profit'] for r in yearly)
    tot_rr = tot_r/tot_b*100 if tot_b>0 else 0
    tot_h = sum(r['hits'] for r in yearly)
    tot_races = sum(r['races'] for r in yearly)
    p(f'  通算: {tot_races}R 的中{tot_h} 回収{tot_rr:.1f}%')

    all_results.append({'lb':lb, 'yearly':yearly, 'total_rr':tot_rr, 'total_races':tot_races})

# ルックバック別比較
p(f'\n{"="*90}')
p('=== ルックバック期間別の比較 ===')
p(f'{"="*90}')
header = f'{"LB":>3} {"通算":>7}  ' + '  '.join(f'{y}' for y in test_years)
p(header)
p('-'*70)
for r in all_results:
    line = f'{r["lb"]:>2}年 {r["total_rr"]:>6.1f}%  ' + '  '.join(f'{yr["rr"]:>5.1f}%' for yr in r['yearly'])
    p(line)

# 2026年だけの比較
p(f'\n=== 2026年のみ比較 ===')
for r in all_results:
    y26 = [y for y in r['yearly'] if y['year']==2026][0]
    p(f'  直近{r["lb"]}年: 回収率{y26["rr"]:.1f}% 的中{y26["hits"]}/{y26["races"]} 収支{y26["profit"]:+,.0f}円')

db.close(); out.close()
