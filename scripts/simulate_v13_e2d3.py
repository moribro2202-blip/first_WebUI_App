"""
v13: E2(馬体重TYB) + D3(脚質分析)
- TYBから当日馬体重と増減を取得してスコアに反映
- 過去の着順パターンから脚質（先行/差し）を推定
"""
import sqlite3, math, sys, os
from collections import defaultdict
import codecs

out = open(r'C:\Users\moribro2201\Desktop\simulation_v13.txt', 'w', encoding='utf-8')
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

# E2: TYBから馬体重を事前ロード
p('Phase 0: TYBから馬体重ロード...')
tyb_weight = {}  # {race_id: {horse_number: (weight, diff)}}
tyb_dir = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb\TYB'
tyb_count = 0

for fname in sorted(os.listdir(tyb_dir)):
    if not fname.endswith('.txt'): continue
    buf = open(os.path.join(tyb_dir, fname), 'rb').read()
    lines = buf.split(b'\r\n')
    for l in lines:
        if len(l) < 92: continue
        vc = l[0:2].decode(); yr = l[2:4].decode(); kai = l[4:6].decode()
        rn = l[6:8].decode(); hn_str = l[8:10].decode()
        try:
            hn = int(hn_str)
            # pos88-90: 馬体重(3桁), pos91-93: 増減(符号付き)
            wt_str = l[88:91].decode(errors='replace').strip()
            diff_str = l[91:95].decode(errors='replace').strip()
            wt = int(wt_str) if wt_str.isdigit() else 0
            # 増減パース: "+ 6", "- 4", "  0" etc
            diff = 0
            diff_clean = diff_str.replace(' ', '')
            if diff_clean:
                try: diff = int(diff_clean)
                except: pass

            if wt > 300:
                rid_key = f'{yr}{vc}{kai}{rn}'
                if rid_key not in tyb_weight:
                    tyb_weight[rid_key] = {}
                tyb_weight[rid_key][hn] = (wt, diff)
                tyb_count += 1
        except: pass

p(f'  TYBレコード: {tyb_count}, レース数: {len(tyb_weight)}')

# 累積データ
jc=defaultdict(lambda:{'r':0,'w':0}); hr=defaultdict(list)
# D3: 馬の着順パターン（先行力の指標）
horse_early_power = defaultdict(list)  # 各レースでの相対位置

for rid,rd,vc,sf,dt in races:
    if rd>='2026-01-01': break
    res=db.execute('SELECT horse_number,finish_position,horse_id,finish_time FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
    if len(res) < 3: continue

    # D3: レース内の相対的な走破タイム差から脚質を推定
    times = [(r[0], r[1], r[2], r[3]) for r in res if r[3] and r[3] > 0]
    if len(times) >= 3:
        min_time = min(t[3] for t in times)
        for hn, fp, hid, ft in times:
            if hid:
                # 勝ち馬との差（秒）。小さいほど前にいた可能性が高い
                time_diff = ft - min_time
                # 着順/頭数 で正規化した位置
                rel_pos = fp / len(res)
                horse_early_power[hid].append({
                    'time_diff': time_diff,
                    'rel_pos': rel_pos,
                    'fp': fp,
                    'n': len(res),
                })
                if len(horse_early_power[hid]) > 10:
                    horse_early_power[hid] = horse_early_power[hid][-10:]

    for hn,fp,hid,ft in res:
        ent=entry_cache.get(rid,{}).get(hn,{})
        jn=ent.get('jockey','')
        if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1)
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid])>20: hr[hid]=hr[hid][-20:]

p(f'  騎手: {len(jc)}, 馬: {len(hr)}, 脚質データ: {len(horse_early_power)}')

def base_score(h, rid, vc, sf, dt):
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

models = {
    'v7ベースライン': lambda h,rid,vc,sf,dt,rk: base_score(h,rid,vc,sf,dt),
    'E2: 馬体重': lambda h,rid,vc,sf,dt,rk: base_score(h,rid,vc,sf,dt) + weight_bonus(h,rid,rk),
    'D3: 脚質': lambda h,rid,vc,sf,dt,rk: base_score(h,rid,vc,sf,dt) + running_style_bonus(h,rid),
    'E2+D3': lambda h,rid,vc,sf,dt,rk: base_score(h,rid,vc,sf,dt) + weight_bonus(h,rid,rk) + running_style_bonus(h,rid),
    'E2+D3+乖離フィルタ': lambda h,rid,vc,sf,dt,rk: base_score(h,rid,vc,sf,dt) + weight_bonus(h,rid,rk) + running_style_bonus(h,rid),
}

def weight_bonus(h, rid, race_key):
    """E2: 馬体重ボーナス。大幅増減を減点"""
    tw = tyb_weight.get(race_key, {}).get(h)
    if not tw: return 0
    wt, diff = tw
    bonus = 0
    if abs(diff) >= 20: bonus = -6  # 20kg以上変動は大減点
    elif abs(diff) >= 10: bonus = -3  # 10kg以上は減点
    elif abs(diff) <= 2: bonus = 1   # 安定は微加点
    return bonus

def running_style_bonus(h, rid):
    """D3: 脚質ボーナス。安定して上位に来る馬（先行力）を加点"""
    ent = entry_cache.get(rid, {}).get(h, {})
    hid = ent.get('hid', '')
    if not hid or hid not in horse_early_power: return 0
    recs = horse_early_power[hid]
    if len(recs) < 3: return 0
    # 平均相対位置（0に近いほど前にいる）
    avg_rel = sum(r['rel_pos'] for r in recs[-5:]) / len(recs[-5:])
    # 安定性（分散が小さいほど安定）
    positions = [r['fp'] for r in recs[-5:]]
    mean_pos = sum(positions) / len(positions)
    variance = sum((p - mean_pos)**2 for p in positions) / len(positions)
    stability = max(0, 3 - variance**0.5) * 0.5  # 安定なら加点
    return stability

p('\nPhase 2: シミュレーション...\n')
all_results = []

for mname, score_fn in models.items():
    use_d2_filter = '乖離' in mname
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

        race_key = rid  # race_idをそのまま使う
        sc=[score_fn(h,rid,vc,sf,dt,race_key) for h in hl]
        mp=softmax(sc); mkp=mktp(early); bp=blendf(mp,mkp)
        rk=sorted(range(len(hl)),key=lambda i:-bp[i])
        top=[hl[r] for r in rk[:3]]

        # D2フィルタ
        if use_d2_filter:
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

p(f'{"#":>3} {"モデル":<25} {"R数":>5} {"的中":>4} {"的中率":>6} {"収支":>13} {"回収率":>7}')
p('-'*75)
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])):
    hr_=r['hits']/r['races']*100 if r['races']>0 else 0
    p(f'{i+1:>3} {r["name"]:<25} {r["races"]:>5} {r["hits"]:>4} {hr_:>5.1f}% {r["profit"]:>+12,.0f}円 {r["rr"]:>6.1f}%')

# 上位の月別
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])[:2]):
    p(f'\n--- {i+1}位: {r["name"]} ---')
    cb=0;cr=0
    for m in sorted(r['mo'].keys()):
        d=r['mo'][m]; cb+=d['b'];cr+=d['r']
        p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

db.close(); out.close()
