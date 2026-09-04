"""
v15: 調教データ（CHA）を使ったシミュレーション
CHAの数値フィールドを特徴量として追加し、v7ベースラインと比較
"""
import sqlite3, math, sys, os
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v15.txt', 'w', encoding='utf-8')
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
def blendf(m,mk,alpha):
    bl=[math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p_/s for p_ in bl] if s>0 else bl

# CHA全ファイルロード
p('Phase 0: CHAデータロード...')
cha_data = {}  # {race_key: {horse_number: [field values]}}
cha_dir = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb\CHA'

for fname in sorted(os.listdir(cha_dir)):
    if not fname.endswith('.txt'): continue
    buf = open(os.path.join(cha_dir, fname), 'rb').read()
    for l in buf.split(b'\r\n'):
        if len(l) < 50: continue
        try:
            rk = l[0:8].decode()
            hn = int(l[8:10].decode())
            # 数値フィールドを抽出（pos20以降）
            fields = []
            for s in range(20, min(55, len(l)), 5):
                chunk = l[s:s+5].decode(errors='replace').strip()
                # 数値っぽいものだけ抽出
                try:
                    v = float(chunk) if chunk else 0
                    fields.append(v)
                except:
                    # スペース区切りの複数値を分解
                    parts = chunk.split()
                    for pp in parts:
                        try: fields.append(float(pp))
                        except: fields.append(0)
            if rk not in cha_data: cha_data[rk] = {}
            cha_data[rk][hn] = fields
        except: pass

p(f'  CHAレコード: {sum(len(v) for v in cha_data.values())}, レース数: {len(cha_data)}')

# 調教スコアの計算：各馬の調教フィールドをレース内で偏差値化
def get_cha_score(rid, hn):
    """CHAデータから調教スコアを算出"""
    race_cha = cha_data.get(rid, {})
    if not race_cha or hn not in race_cha:
        return 0

    horse_fields = race_cha[hn]
    if not horse_fields:
        return 0

    # 全馬の同じフィールドの平均・標準偏差を計算し、偏差値化
    all_fields = list(race_cha.values())
    if len(all_fields) < 3:
        return 0

    # 各フィールドの偏差値を平均
    z_scores = []
    for fi in range(min(len(horse_fields), 7)):
        vals = [f[fi] for f in all_fields if len(f) > fi and f[fi] != 0]
        if len(vals) < 3: continue
        mean = sum(vals) / len(vals)
        std = (sum((v-mean)**2 for v in vals) / len(vals)) ** 0.5
        if std < 0.01: continue
        if fi < len(horse_fields) and horse_fields[fi] != 0:
            z = (horse_fields[fi] - mean) / std
            z_scores.append(z)

    if not z_scores:
        return 0

    # 平均z-scoreを調教ボーナスに変換（zが低い=タイムが速い=良い場合もある）
    # 調教タイムは低いほど良いので、符号を反転
    avg_z = sum(z_scores) / len(z_scores)
    return -avg_z * 2  # 偏差値スケールに変換

# 標準モデル
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

p('\nPhase 1: シミュレーション...\n')

models = {
    'v7ベースライン': (0.15, 0),
    'CHA重み1.0 alpha0.15': (0.15, 1.0),
    'CHA重み2.0 alpha0.15': (0.15, 2.0),
    'CHA重み3.0 alpha0.15': (0.15, 3.0),
    'CHA重み5.0 alpha0.15': (0.15, 5.0),
    'CHA重み2.0 alpha0.10': (0.10, 2.0),
    'CHA重み2.0 alpha0.20': (0.20, 2.0),
    'CHA重み2.0 alpha0.25': (0.25, 2.0),
    'CHA重み3.0 alpha0.20': (0.20, 3.0),
    'CHA重み5.0 alpha0.20': (0.20, 5.0),
    'CHAのみ alpha0.15': (0.15, -1),  # special: CHA only
    'CHA重み2.0+乖離': (0.15, 2.0),  # with D2 filter
}

all_results = []

for mname, (alpha, cha_weight) in models.items():
    use_d2 = '乖離' in mname
    cha_only = cha_weight == -1
    cw = abs(cha_weight) if not cha_only else 5.0

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

        if cha_only:
            sc=[50.0 + get_cha_score(rid, h) * cw for h in hl]
        else:
            sc=[base_score(h,rid,vc,sf,dt) + get_cha_score(rid, h) * cw for h in hl]

        mp=softmax(sc); mkp=mktp(early); bp=blendf(mp,mkp,alpha)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        top=[hl[r] for r in rk[:3]]

        if use_d2:
            mkt_top=sorted(hl,key=lambda h:om[h])[:3]
            if set(top)==set(mkt_top): continue

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue
        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=BUDGET;traces+=1
        month=rd[:7]; mo[month]['b']+=BUDGET; mo[month]['n']+=1
        if hit: tr+=BUDGET*odds; thits+=1; mo[month]['r']+=BUDGET*odds

    rr=tr/tb*100 if tb>0 else 0
    all_results.append({'name':mname,'rr':rr,'tb':tb,'tr':tr,'profit':tr-tb,'races':traces,'hits':thits,'mo':dict(mo)})

p(f'{"#":>3} {"モデル":<30} {"R数":>5} {"的中":>4} {"的中率":>6} {"収支":>13} {"回収率":>7}')
p('-'*80)
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])):
    hr_=r['hits']/r['races']*100 if r['races']>0 else 0
    p(f'{i+1:>3} {r["name"]:<30} {r["races"]:>5} {r["hits"]:>4} {hr_:>5.1f}% {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

# 上位3の月別
p(f'\n=== 上位3の月別 ===')
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])[:3]):
    p(f'\n--- {i+1}位: {r["name"]} (回収率{r["rr"]:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(r['mo'].keys()):
        d=r['mo'][m]; cb+=d['b'];cr+=d['r']
        p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

db.close(); out.close()
