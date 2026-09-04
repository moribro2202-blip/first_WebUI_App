"""
v7改: 全券種・全戦略の補正なしシミュレーション
条件: リアルタイム再現、ウォークフォワード、SM不使用、補正なし
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\simulation_v7_all.txt', 'w', encoding='utf-8')
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
def check_hit(bt,parts,top3):
    if bt=='sanrenpuku': return set(parts)==set(top3[:3])
    elif bt=='umaren': return set(parts)==set(top3[:2])
    elif bt=='win': return parts[0]==top3[0]
    elif bt=='wide': return parts[0] in top3 and parts[1] in top3
    elif bt=='umatan': return parts[0]==top3[0] and parts[1]==top3[1]
    elif bt=='sanrentan': return list(parts)==list(top3[:3])
    return False

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

strategies = {
    '単勝◎ 1点': lambda t: [('win',[t[0]],10000)],
    '単勝◎○ 2点': lambda t: [('win',[t[0]],6000),('win',[t[1]],4000)],
    '馬連◎○ 1点': lambda t: [('umaren',sorted(t[:2]),10000)],
    '馬連◎○▲ 3点': lambda t: [
        ('umaren',sorted(t[:2]),4000),('umaren',sorted([t[0],t[2]]),3000),('umaren',sorted([t[1],t[2]]),3000)],
    '馬連◎流し5点': lambda t: [
        ('umaren',sorted([t[0],t[1]]),3000),('umaren',sorted([t[0],t[2]]),2500),
        ('umaren',sorted([t[0],t[3]]),2000),('umaren',sorted([t[0],t[4]]),1500),
        ('umaren',sorted([t[0],t[5]]),1000)] if len(t)>=6 else [],
    '馬単◎→○ 1点': lambda t: [('umatan',[t[0],t[1]],10000)],
    '馬単◎→○,◎→▲ 2点': lambda t: [('umatan',[t[0],t[1]],5000),('umatan',[t[0],t[2]],5000)],
    'ワイド◎○ 1点': lambda t: [('wide',sorted(t[:2]),10000)],
    'ワイド◎○▲ 3点': lambda t: [
        ('wide',sorted(t[:2]),4000),('wide',sorted([t[0],t[2]]),3000),('wide',sorted([t[1],t[2]]),3000)],
    'ワイド◎○▲△ 6点': lambda t: [
        ('wide',sorted([t[0],t[1]]),2500),('wide',sorted([t[0],t[2]]),2000),
        ('wide',sorted([t[0],t[3]]),1500),('wide',sorted([t[1],t[2]]),1500),
        ('wide',sorted([t[1],t[3]]),1500),('wide',sorted([t[2],t[3]]),1000)] if len(t)>=4 else [],
    '三連複◎○▲ 1点': lambda t: [('sanrenpuku',sorted(t[:3]),10000)],
    '三連複◎○▲△ 4点': lambda t: [
        ('sanrenpuku',sorted(t[:3]),4000),('sanrenpuku',sorted([t[0],t[1],t[3]]),2000),
        ('sanrenpuku',sorted([t[0],t[2],t[3]]),2000),('sanrenpuku',sorted([t[1],t[2],t[3]]),2000)] if len(t)>=4 else [],
    '三連単◎→○→▲ 1点': lambda t: [('sanrentan',[t[0],t[1],t[2]],10000)],
    '三連単◎軸6点': lambda t: [
        ('sanrentan',[t[0],t[1],t[2]],3000),('sanrentan',[t[0],t[2],t[1]],2000),
        ('sanrentan',[t[1],t[0],t[2]],2000),('sanrentan',[t[1],t[2],t[0]],1000),
        ('sanrentan',[t[2],t[0],t[1]],1000),('sanrentan',[t[2],t[1],t[0]],1000)],
    'MIX 単勝+三連複': lambda t: [('win',[t[0]],3000),('sanrenpuku',sorted(t[:3]),7000)],
    'MIX 馬連+三連複': lambda t: [('umaren',sorted(t[:2]),4000),('sanrenpuku',sorted(t[:3]),6000)],
    'MIX ワイド+三連複': lambda t: [('wide',sorted(t[:2]),4000),('sanrenpuku',sorted(t[:3]),6000)],
    'MIX 単馬連三複': lambda t: [
        ('win',[t[0]],2000),('umaren',sorted(t[:2]),3000),('sanrenpuku',sorted(t[:3]),5000)],
    'MIX 全券種': lambda t: [
        ('win',[t[0]],1000),('umaren',sorted(t[:2]),1500),('umatan',[t[0],t[1]],1500),
        ('wide',sorted(t[:2]),1000),('sanrenpuku',sorted(t[:3]),3000),('sanrentan',[t[0],t[1],t[2]],2000)],
}

all_results = []

for sname, sfn in strategies.items():
    tb=0;tr=0;traces=0;thits=0;tbets=0
    mo=defaultdict(lambda:{'b':0,'r':0,'n':0})
    bt_stats=defaultdict(lambda:{'b':0,'r':0,'h':0,'c':0})

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
        top=[hl[r] for r in rk[:min(6,len(rk))]]
        if len(top)<3: continue

        bets=sfn(top)
        if not bets: continue
        month=rd[:7]; rb=0;rr=0
        for bt,parts,amt in bets:
            combo='-'.join(str(x) for x in parts)
            orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",(rid,bt,combo)).fetchone()
            if not orow or orow[0]<=0: continue
            odds=orow[0]  # 補正なし
            hit=check_hit(bt,parts,t3)
            rb+=amt; tbets+=1; bt_stats[bt]['c']+=1; bt_stats[bt]['b']+=amt
            if hit: rr+=amt*odds; thits+=1; bt_stats[bt]['h']+=1; bt_stats[bt]['r']+=amt*odds
        if rb==0: continue
        tb+=rb;tr+=rr;traces+=1
        mo[month]['b']+=rb;mo[month]['r']+=rr;mo[month]['n']+=1

    rr_pct=tr/tb*100 if tb>0 else 0
    hr_pct=thits/tbets*100 if tbets>0 else 0
    all_results.append({
        'name':sname,'rr':rr_pct,'tb':tb,'tr':tr,'profit':tr-tb,
        'races':traces,'hits':thits,'bets':tbets,'hr':hr_pct,
        'mo':dict(mo),'bt':dict(bt_stats),
    })

p('='*120)
p('=== v7改: 全券種・全戦略シミュレーション（補正なし・リーク排除・alpha=0.15） ===')
p('='*120)
p(f'{"#":>3} {"戦略":<25} {"R数":>5} {"点数":>6} {"的中":>5} {"的中率":>6} {"投資":>14} {"払戻":>14} {"収支":>14} {"回収率":>7}')
p('-'*110)
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])):
    p(f'{i+1:>3} {r["name"]:<25} {r["races"]:>5} {r["bets"]:>6} {r["hits"]:>5} {r["hr"]:>5.1f}% {r["tb"]:>13,.0f}円 {r["tr"]:>13,.0f}円 {r["profit"]:>+13,.0f}円 {r["rr"]:>6.1f}%')

# 上位5の月別
p(f'\n{"="*80}')
p('=== 上位5の月別推移 ===')
p(f'{"="*80}')
for i,r in enumerate(sorted(all_results,key=lambda x:-x['rr'])[:5]):
    p(f'\n--- {i+1}位: {r["name"]} (回収率{r["rr"]:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(r['mo'].keys()):
        d=r['mo'][m]; cb+=d['b'];cr+=d['r']
        p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')
    # 券種別
    lb={'win':'単勝','umaren':'馬連','wide':'ワイド','umatan':'馬単','sanrenpuku':'三連複','sanrentan':'三連単'}
    for bt in ['win','umaren','wide','umatan','sanrenpuku','sanrentan']:
        bs=r['bt'].get(bt)
        if not bs or bs['c']==0: continue
        p(f'  {lb.get(bt,bt)}: {bs["c"]:,}点 的中{bs["h"]:,} 回収{bs["r"]/bs["b"]*100 if bs["b"]>0 else 0:.1f}%')

db.close(); out.close()
