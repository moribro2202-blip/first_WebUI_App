"""
v18: 短期ルックバックの検証
直近3ヶ月、6ヶ月、9ヶ月、1年、1.5年、2年を比較
"""
import sqlite3, math, sys
from collections import defaultdict
from datetime import datetime, timedelta

out = open(r'C:\Users\moribro2201\Desktop\simulation_v18.txt', 'w', encoding='utf-8')
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

p('=== v18: 短期ルックバック検証 ===\n')

# ルックバック期間（月数）
lookbacks_months = [3, 6, 9, 12, 18, 24, 36]
test_years = [2021, 2022, 2023, 2024, 2025, 2026]

all_results = []

for lb_months in lookbacks_months:
    yearly = []

    for test_year in test_years:
        test_start = f'{test_year}-01-01'
        test_end = f'{test_year+1}-01-01'

        # 学習期間: テスト年の開始日からlb_months前
        dt_start = datetime(test_year, 1, 1) - timedelta(days=lb_months*30)
        train_start = dt_start.strftime('%Y-%m-%d')
        train_end = test_start

        # 累積リセット
        jc = defaultdict(lambda:{'r':0,'w':0})
        hr = defaultdict(list)

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

    tot_b = sum(r['races'] for r in yearly)*BUDGET
    tot_r = tot_b + sum(r['profit'] for r in yearly)
    tot_rr = tot_r/tot_b*100 if tot_b>0 else 0

    all_results.append({'lb':lb_months, 'yearly':yearly, 'total_rr':tot_rr})

    lb_label = f'{lb_months}ヶ月' if lb_months < 12 else f'{lb_months//12}年' if lb_months%12==0 else f'{lb_months}ヶ月'
    p(f'--- {lb_label} ---')
    for r in yearly:
        hr_ = r['hits']/r['races']*100 if r['races']>0 else 0
        p(f'  {r["year"]}: {r["races"]:>5}R 的中{r["hits"]:>4} ({hr_:.1f}%) 回収{r["rr"]:.1f}% 収支{r["profit"]:+,.0f}円')
    p(f'  通算: 回収{tot_rr:.1f}%')
    p()

# 比較表
p(f'\n{"="*90}')
p('=== ルックバック期間別の年別回収率 ===')
p(f'{"="*90}')

header = f'{"期間":>6} {"通算":>6}  ' + '  '.join(f'{y}' for y in test_years)
p(header)
p('-'*75)
for r in all_results:
    lb = r['lb']
    lb_label = f'{lb}M' if lb < 12 else f'{lb//12}Y' if lb%12==0 else f'{lb}M'
    line = f'{lb_label:>6} {r["total_rr"]:>5.1f}%  ' + '  '.join(f'{yr["rr"]:>5.1f}%' for yr in r['yearly'])
    p(line)

# 2026年のみ
p(f'\n=== 2026年のみ ===')
for r in all_results:
    lb = r['lb']
    y26 = [y for y in r['yearly'] if y['year']==2026][0]
    lb_label = f'{lb}ヶ月' if lb < 12 else f'{lb//12}年' if lb%12==0 else f'{lb}ヶ月'
    p(f'  直近{lb_label:<5}: 回収率{y26["rr"]:>6.1f}% 的中{y26["hits"]:>3}/{y26["races"]} 収支{y26["profit"]:>+11,.0f}円')

# プラスの年が多いルックバックを特定
p(f'\n=== プラス年数カウント ===')
for r in all_results:
    lb = r['lb']
    plus_years = sum(1 for y in r['yearly'] if y['rr'] >= 100)
    lb_label = f'{lb}ヶ月' if lb < 12 else f'{lb//12}年' if lb%12==0 else f'{lb}ヶ月'
    plus_list = [str(y['year']) for y in r['yearly'] if y['rr'] >= 100]
    p(f'  直近{lb_label:<5}: {plus_years}/6年プラス ({", ".join(plus_list) if plus_list else "なし"})')

db.close(); out.close()
