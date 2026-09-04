"""
v8: 改善提案A1〜A4のシミュレーション
A1: レースフィルタリング（確信度で絞り込み）
A2: 馬体重変動（±10kg以上の馬を除外して上位3頭を選び直し）
A3: 騎手×調教師の相性
A4: 前走からの間隔（長期休養明けを減点）
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v8.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
BETA=1.03; L2=0.8; L3=0.6; BUDGET=10000; ALPHA=0.15; SCALE=0.15

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

# データロード
races=db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache={}
for rid,_,_,_,_ in races:
    es=db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid]={e[0]:{'hid':e[1],'jockey':e[2],'trainer':e[3]} for e in es}

# 累積データ
jc=defaultdict(lambda:{'r':0,'w':0})
hr=defaultdict(list)
# A3: 騎手×調教師
jt_combo=defaultdict(lambda:{'r':0,'w':0})
# A4: 馬の最終出走日
horse_last_race={}

for rid,rd,vc,sf,dt in races:
    if rd>='2026-01-01': break
    res=db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
    for hn,fp,hid in res:
        ent=entry_cache.get(rid,{}).get(hn,{})
        jn=ent.get('jockey',''); tn=ent.get('trainer','')
        if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
        if jn and tn:
            k=f'{jn}:{tn}'; jt_combo[k]['r']+=1
            if fp==1: jt_combo[k]['w']+=1
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid])>20: hr[hid]=hr[hid][-20:]
            horse_last_race[hid]=rd

p(f'Init: {len(jc)} jockeys, {len(hr)} horses, {len(jt_combo)} jockey-trainer combos')

# A2: 馬体重データ（TYBは未パース。SEDの馬体重を使用）
horse_last_weight={}
rows=db.execute('''
    SELECT r.horse_id, r.horse_weight, ra.race_date
    FROM results r JOIN races ra ON r.race_id=ra.race_id
    WHERE r.horse_id IS NOT NULL AND r.horse_weight IS NOT NULL AND r.horse_weight > 0
    AND ra.race_date < '2026-01-01'
    ORDER BY ra.race_date
''').fetchall()
for hid, wt, rd in rows:
    horse_last_weight[hid] = wt
p(f'Horse weights: {len(horse_last_weight)}')

def base_score(h, rid, vc, sf, dt, use_jt=False, use_interval=False):
    base=50.0; ent=entry_cache.get(rid,{}).get(h,{})
    hid=ent.get('hid',''); jn=ent.get('jockey',''); tn=ent.get('trainer','')
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
    # A3: 騎手×調教師
    jtb=0
    if use_jt and jn and tn:
        k=f'{jn}:{tn}'
        if k in jt_combo and jt_combo[k]['r']>=10:
            jtb=(jt_combo[k]['w']/jt_combo[k]['r']-0.08)*30
    # A4: 前走間隔
    intb=0
    if use_interval and hid and hid in horse_last_race:
        from datetime import datetime
        try:
            rd_obj=datetime.strptime(entry_cache.get(rid,{}).get('_date','2026-01-01'),'%Y-%m-%d')
        except:
            intb=0
    return base+jb+hb+db_+sb+vb+tb+jtb+intb

def run_sim(name, score_fn, filter_fn=None, weight_filter=False):
    tb=0;tr=0;traces=0;thits=0
    mo=defaultdict(lambda:{'b':0,'r':0,'n':0})
    skipped=0

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
        sc=[score_fn(h,rid,vc,sf,dt) for h in hl]

        # A2: 馬体重フィルタ - 大幅増減の馬をスコア減点
        if weight_filter:
            for i,h in enumerate(hl):
                ent=entry_cache.get(rid,{}).get(h,{})
                hid=ent.get('hid','')
                if hid and hid in horse_last_weight:
                    # 現在の馬体重はSEDから取得
                    cur_w=db.execute("SELECT horse_weight FROM results WHERE race_id=? AND horse_number=?",(rid,h)).fetchone()
                    if cur_w and cur_w[0] and cur_w[0]>0:
                        diff=abs(cur_w[0]-horse_last_weight[hid])
                        if diff>=10: sc[i]-=5  # 大幅変動は減点
                        if diff>=20: sc[i]-=10

        mp=softmax(sc); mkp=mktp(early); bp=blendf(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        top=[hl[r] for r in rk[:3]]

        # A1: フィルタリング
        if filter_fn:
            top3_probs=[bp[rk[i]] for i in range(3)]
            if not filter_fn(top3_probs, bp):
                skipped+=1; continue

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue
        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=BUDGET;traces+=1
        month=rd[:7]; mo[month]['b']+=BUDGET; mo[month]['n']+=1
        if hit: tr+=BUDGET*odds; thits+=1; mo[month]['r']+=BUDGET*odds

    rr=tr/tb*100 if tb>0 else 0
    return {'name':name,'rr':rr,'tb':tb,'tr':tr,'profit':tr-tb,'races':traces,'hits':thits,'skipped':skipped,'mo':dict(mo)}

# ベースライン（v7と同じ）
p('\n=== v8: 改善提案シミュレーション ===\n')

results = []

# ベースライン
results.append(run_sim('v7ベースライン',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt)))

# A1: レースフィルタリング
# A1-a: 上位3頭の合計確率が40%以上
results.append(run_sim('A1-a: top3合計≥40%',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: sum(t3p)>=0.40))

# A1-b: 上位3頭の合計確率が50%以上
results.append(run_sim('A1-b: top3合計≥50%',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: sum(t3p)>=0.50))

# A1-c: 上位3頭の合計確率が60%以上
results.append(run_sim('A1-c: top3合計≥60%',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: sum(t3p)>=0.60))

# A1-d: 1位と4位の確率差が5%以上
results.append(run_sim('A1-d: 1位-4位差≥5%',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: (sorted(bp,reverse=True)[0]-sorted(bp,reverse=True)[3])>=0.05 if len(bp)>=4 else True))

# A1-e: 1位と4位の確率差が10%以上
results.append(run_sim('A1-e: 1位-4位差≥10%',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: (sorted(bp,reverse=True)[0]-sorted(bp,reverse=True)[3])>=0.10 if len(bp)>=4 else True))

# A1-f: 頭数10頭以上のみ
results.append(run_sim('A1-f: 頭数≥10',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: len(bp)>=10))

# A1-g: 頭数12頭以上のみ
results.append(run_sim('A1-g: 頭数≥12',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    filter_fn=lambda t3p,bp: len(bp)>=12))

# A2: 馬体重変動
results.append(run_sim('A2: 馬体重変動考慮',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt),
    weight_filter=True))

# A3: 騎手×調教師の相性
results.append(run_sim('A3: 騎手×調教師追加',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt,use_jt=True)))

# A4: 前走間隔（SED resultsの日付差で計算）
# A4は直接的にはスコアに反映しにくいので、長期休養馬を減点する別実装
def score_with_interval(h, rid, vc, sf, dt):
    s = base_score(h, rid, vc, sf, dt)
    ent = entry_cache.get(rid, {}).get(h, {})
    hid = ent.get('hid', '')
    if hid and hid in horse_last_race:
        try:
            from datetime import datetime
            last = datetime.strptime(horse_last_race[hid], '%Y-%m-%d')
            # ridからrace_dateを取得
            rd_row = db.execute("SELECT race_date FROM races WHERE race_id=?", (rid,)).fetchone()
            if rd_row:
                cur = datetime.strptime(rd_row[0], '%Y-%m-%d')
                days = (cur - last).days
                if days > 180: s -= 8  # 6ヶ月以上
                elif days > 90: s -= 4  # 3ヶ月以上
        except: pass
    return s

results.append(run_sim('A4: 長期休養減点', score_with_interval))

# 組み合わせ: A1-b + A2 + A3 + A4
def score_all(h, rid, vc, sf, dt):
    s = base_score(h, rid, vc, sf, dt, use_jt=True)
    ent = entry_cache.get(rid, {}).get(h, {})
    hid = ent.get('hid', '')
    if hid and hid in horse_last_race:
        try:
            from datetime import datetime
            rd_row = db.execute("SELECT race_date FROM races WHERE race_id=?", (rid,)).fetchone()
            if rd_row:
                cur = datetime.strptime(rd_row[0], '%Y-%m-%d')
                last = datetime.strptime(horse_last_race[hid], '%Y-%m-%d')
                days = (cur - last).days
                if days > 180: s -= 8
                elif days > 90: s -= 4
        except: pass
    return s

results.append(run_sim('ALL: A1b+A2+A3+A4', score_all,
    filter_fn=lambda t3p,bp: sum(t3p)>=0.50,
    weight_filter=True))

# A1-a + A3 + A4
results.append(run_sim('A1a+A3+A4', score_all,
    filter_fn=lambda t3p,bp: sum(t3p)>=0.40))

# A1-d + A3
results.append(run_sim('A1d+A3',
    lambda h,rid,vc,sf,dt: base_score(h,rid,vc,sf,dt,use_jt=True),
    filter_fn=lambda t3p,bp: (sorted(bp,reverse=True)[0]-sorted(bp,reverse=True)[3])>=0.05 if len(bp)>=4 else True))

# ランキング
p(f'{"#":>3} {"モデル":<25} {"R数":>5} {"skip":>5} {"的中":>4} {"的中率":>6} {"投資":>13} {"収支":>13} {"回収率":>7}')
p('-'*90)
for i,r in enumerate(sorted(results,key=lambda x:-x['rr'])):
    hr_pct=r['hits']/r['races']*100 if r['races']>0 else 0
    p(f'{i+1:>3} {r["name"]:<25} {r["races"]:>5} {r["skipped"]:>5} {r["hits"]:>4} {hr_pct:>5.1f}% {r["tb"]:>12,.0f}円 {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

# 上位3の月別
p(f'\n=== 上位3の月別推移 ===')
for i,r in enumerate(sorted(results,key=lambda x:-x['rr'])[:3]):
    p(f'\n--- {i+1}位: {r["name"]} (回収率{r["rr"]:.1f}%, {r["races"]}R) ---')
    cb=0;cr=0
    for m in sorted(r['mo'].keys()):
        d=r['mo'][m]; cb+=d['b'];cr+=d['r']
        p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

# 成績更新（ウォークフォワード）
for rid,rd,vc,sf,dt in races:
    if rd<'2026-01-01': continue
    res=db.execute('SELECT horse_number,finish_position,horse_id,horse_weight FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
    for hn,fp,hid,wt in res:
        ent=entry_cache.get(rid,{}).get(hn,{})
        jn=ent.get('jockey',''); tn=ent.get('trainer','')
        if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
        if jn and tn:
            k=f'{jn}:{tn}'; jt_combo[k]['r']+=1
            if fp==1: jt_combo[k]['w']+=1
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid])>20: hr[hid]=hr[hid][-20:]
            horse_last_race[hid]=rd
            if wt and wt>0: horse_last_weight[hid]=wt

db.close(); out.close()
