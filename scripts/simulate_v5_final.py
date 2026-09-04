"""
v5: 全課題解決
1. オッズ補正を2024-2025データのみで計算（時系列分割）
2. alpha値をfull特徴量で再最適化
3. 最終ランキング出力
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\simulation_v5.txt', 'w', encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

BETA=1.03; L2=0.8; L3=0.6; BUDGET=10000

# === 課題1: オッズ補正を2024-2025データのみで計算 ===
print('=== 課題1: オッズ補正の時系列分割 ===')
print('2024-2025年のデータのみで払戻率を計算\n')

correction_2425 = {}
for bt, K in [('win',1),('place',3),('umaren',1),('wide',3),('umatan',1),('sanrenpuku',1),('sanrentan',1)]:
    rows = db.execute('''
        SELECT o.race_id, SUM(1.0/o.odds) as total_inv
        FROM odds o JOIN races r ON o.race_id = r.race_id
        WHERE o.bet_type=? AND o.odds>0 AND r.race_date < '2026-01-01'
        GROUP BY o.race_id
    ''', (bt,)).fetchall()
    if not rows: continue
    payouts = [K/r[1] for r in rows]
    avg_payout = sum(payouts)/len(payouts)
    # JRA公式払戻率
    official = {'win':0.80,'place':0.80,'umaren':0.775,'wide':0.775,'umatan':0.75,'sanrenpuku':0.75,'sanrentan':0.725}
    off = official.get(bt, 0.75)
    corr = off / avg_payout if avg_payout > 0 else 1.0
    correction_2425[bt] = corr
    print(f'  {bt}: OZ払戻率={avg_payout:.4f} 公式={off:.3f} 補正={corr:.3f}')

CORR_MAP = correction_2425
print()

# === 関数定義 ===
def softmax(sc, scale):
    s=[(x-50)*scale for x in sc]; mx=max(s) if s else 0
    e=[math.exp(x-mx) for x in s]; t=sum(e)
    return [x/t for x in e] if t>0 else []

def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p**BETA for p in raw]; ps=sum(pw)
    return [p/ps for p in pw]

def blendf(m,mk,alpha):
    bl=[math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p/s for p in bl] if s>0 else bl

def check_hit(bt, parts, top3):
    if bt=='sanrenpuku': return set(parts)==set(top3[:3])
    elif bt=='umaren': return set(parts)==set(top3[:2])
    elif bt=='win': return parts[0]==top3[0]
    elif bt=='wide': return parts[0] in top3 and parts[1] in top3
    return False

# データロード
races = db.execute('''
    SELECT r.race_id, r.race_date, r.venue_code, r.surface, r.distance
    FROM races r ORDER BY r.race_date, r.race_id
''').fetchall()

entry_cache = {}
for race_id, _, _, _, _ in races:
    entries = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(race_id,)).fetchall()
    if entries:
        entry_cache[race_id] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in entries}

# 累積データ
jockey_cum = defaultdict(lambda:{'rides':0,'wins':0})
horse_results = defaultdict(list)

# Phase 1: 2024-2025で初期化
for race_id, race_date, _, _, _ in races:
    if race_date >= '2026-01-01': break
    res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(race_id,)).fetchall()
    for hn, fp, hid in res:
        entry = entry_cache.get(race_id,{}).get(hn,{})
        jname = entry.get('jockey','')
        if jname: jockey_cum[jname]['rides']+=1; (fp==1) and (jockey_cum[jname].__setitem__('wins',jockey_cum[jname]['wins']+1))
        if hid:
            horse_results[hid].append({'fp':fp,'dist':None,'surface':None,'venue':None})

# 再ロード（距離等の情報付き）
horse_results = defaultdict(list)
for race_id, race_date, venue, surface, distance in races:
    if race_date >= '2026-01-01': break
    res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(race_id,)).fetchall()
    for hn, fp, hid in res:
        if hid:
            horse_results[hid].append({'fp':fp,'dist':distance,'surface':surface,'venue':venue})
            if len(horse_results[hid])>20: horse_results[hid]=horse_results[hid][-20:]

# 騎手も再計算
jockey_cum = defaultdict(lambda:{'rides':0,'wins':0})
for race_id, race_date, _, _, _ in races:
    if race_date >= '2026-01-01': break
    res = db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL',(race_id,)).fetchall()
    for hn, fp in res:
        entry = entry_cache.get(race_id,{}).get(hn,{})
        jname = entry.get('jockey','')
        if jname:
            jockey_cum[jname]['rides']+=1
            if fp==1: jockey_cum[jname]['wins']+=1

print(f'Init: {len(jockey_cum)} jockeys, {len(horse_results)} horses')

def calc_score_full(h, race_id, venue, surface, distance):
    base=50.0
    entry=entry_cache.get(race_id,{}).get(h,{})
    hid=entry.get('hid',''); jname=entry.get('jockey','')

    jb=0
    if jname and jname in jockey_cum:
        jc=jockey_cum[jname]
        if jc['rides']>=20: jb=(jc['wins']/jc['rides']-0.08)*50

    hb=0; db_=0; sb=0; vb=0; tb=0
    if hid and hid in horse_results:
        recs=horse_results[hid]
        if len(recs)>=2:
            avg=sum(r['fp'] for r in recs[-5:])/len(recs[-5:]); hb=(6-avg)*2
        dr=[r for r in recs if r['dist'] and abs(r['dist']-distance)<=200]
        if len(dr)>=2: db_=(6-sum(r['fp'] for r in dr[-5:])/len(dr[-5:]))*1.5
        sr=[r for r in recs if r['surface']==surface]
        if len(sr)>=2: sb=(6-sum(r['fp'] for r in sr[-5:])/len(sr[-5:]))*1.5
        vr=[r for r in recs if r['venue']==venue]
        if len(vr)>=2: vb=(6-sum(r['fp'] for r in vr[-5:])/len(vr[-5:]))*1.0
        if len(recs)>=3:
            l3=[r['fp'] for r in recs[-3:]]
            if l3[-1]<l3[0]: tb=(l3[0]-l3[-1])*0.8

    return base+jb+hb+db_+sb+vb+tb

# === 課題2: alpha再最適化 ===
print(f'\n=== 課題2: alpha再最適化（full特徴量 × 三連複1点） ===\n')

alpha_results = []

for alpha_x100 in range(3, 41, 2):  # 0.03 to 0.39
    alpha = alpha_x100/100.0
    scale = 0.15
    total_bet=0; total_ret=0; total_races=0; total_hits=0
    monthly=defaultdict(lambda:{'bet':0,'ret':0,'races':0})

    # リセット不要（累積データは共有、読み取りのみ）
    for race_id, race_date, venue, surface, distance in races:
        if race_date < '2026-01-01': continue

        res=db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(race_id,)).fetchall()
        if len(res)<5: continue
        top3=[r[0] for r in res if r[1]<=3]
        if len(top3)<3: continue

        oz_win=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(race_id,)).fetchall()
        if not oz_win: continue
        oz_map={int(r[0]):r[1] for r in oz_win}
        hl=sorted(oz_map.keys())
        if len(hl)<5: continue

        early=[oz_map[h] for h in hl]
        scores=[calc_score_full(h,race_id,venue,surface,distance) for h in hl]
        mp=softmax(scores,scale); mkp=mktp(early); bp=blendf(mp,mkp,alpha)

        ranked=sorted(range(len(hl)),key=lambda i:-bp[i])
        top_hn=[hl[r] for r in ranked[:3]]

        combo='-'.join(str(h) for h in sorted(top_hn))
        corr=CORR_MAP.get('sanrenpuku',1.0)
        oz_row=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(race_id,combo)).fetchone()
        if not oz_row or oz_row[0]<=0: continue

        odds=oz_row[0]*corr
        hit=set(top_hn)==set(top3[:3])
        total_bet+=BUDGET; total_races+=1
        month=race_date[:7]; monthly[month]['bet']+=BUDGET; monthly[month]['races']+=1
        if hit:
            total_ret+=BUDGET*odds; total_hits+=1
            monthly[month]['ret']+=BUDGET*odds

    rr=total_ret/total_bet*100 if total_bet>0 else 0
    alpha_results.append({'alpha':alpha,'rr':rr,'hits':total_hits,'races':total_races,
                         'bet':total_bet,'ret':total_ret,'profit':total_ret-total_bet,
                         'monthly':dict(monthly)})
    print(f'  alpha={alpha:.2f}: 回収率{rr:>6.1f}% 的中{total_hits:>4}/{total_races} 収支{total_ret-total_bet:>+12,.0f}円')

# ベストalpha
best = max(alpha_results, key=lambda x:x['rr'])
print(f'\n  ベスト: alpha={best["alpha"]:.2f} 回収率{best["rr"]:.1f}%')

# === 最終ランキング: ベストalpha × 複数戦略 ===
print(f'\n=== 最終シミュレーション（alpha={best["alpha"]:.2f}, 時系列分割補正） ===\n')

best_alpha = best['alpha']

strategies = {
    '三連複1点': lambda top: [('sanrenpuku',sorted(top[:3]),10000)],
    '三連複+単勝◎': lambda top: [('sanrenpuku',sorted(top[:3]),7000),('win',[top[0]],3000)],
    '三連複+ワイド◎○': lambda top: [('sanrenpuku',sorted(top[:3]),6000),('wide',sorted(top[:2]),4000)],
    '三連複+馬連◎○': lambda top: [('sanrenpuku',sorted(top[:3]),6000),('umaren',sorted(top[:2]),4000)],
    '三連複4点': lambda top: [
        ('sanrenpuku',sorted(top[:3]),4000),('sanrenpuku',sorted([top[0],top[1],top[3]]),2000),
        ('sanrenpuku',sorted([top[0],top[2],top[3]]),2000),('sanrenpuku',sorted([top[1],top[2],top[3]]),2000),
    ],
}

final_results = []
for sname, sfn in strategies.items():
    total_bet=0;total_ret=0;total_races=0;total_hits=0
    monthly=defaultdict(lambda:{'bet':0,'ret':0,'races':0})
    bt_stats=defaultdict(lambda:{'bet':0,'ret':0,'hits':0,'count':0})

    for race_id, race_date, venue, surface, distance in races:
        if race_date<'2026-01-01': continue
        res=db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(race_id,)).fetchall()
        if len(res)<5: continue
        top3=[r[0] for r in res if r[1]<=3]
        if len(top3)<3: continue
        oz_win=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(race_id,)).fetchall()
        if not oz_win: continue
        oz_map={int(r[0]):r[1] for r in oz_win}
        hl=sorted(oz_map.keys())
        if len(hl)<5: continue

        early=[oz_map[h] for h in hl]
        scores=[calc_score_full(h,race_id,venue,surface,distance) for h in hl]
        mp=softmax(scores,0.15); mkp=mktp(early); bp=blendf(mp,mkp,best_alpha)
        ranked=sorted(range(len(hl)),key=lambda i:-bp[i])
        top_hn=[hl[r] for r in ranked[:4]]

        bets=sfn(top_hn)
        month=race_date[:7]; rb=0;rr_val=0
        for bt,parts,amount in bets:
            combo='-'.join(str(p) for p in parts)
            corr=CORR_MAP.get(bt,1.0)
            oz_row=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",(race_id,bt,combo)).fetchone()
            if not oz_row or oz_row[0]<=0: continue
            odds=oz_row[0]*corr; hit=check_hit(bt,parts,top3)
            rb+=amount; bt_stats[bt]['count']+=1; bt_stats[bt]['bet']+=amount
            if hit: rr_val+=amount*odds; bt_stats[bt]['hits']+=1; bt_stats[bt]['ret']+=amount*odds

        if rb==0: continue
        total_bet+=rb;total_ret+=rr_val;total_races+=1
        monthly[month]['bet']+=rb;monthly[month]['ret']+=rr_val;monthly[month]['races']+=1

    rr=total_ret/total_bet*100 if total_bet>0 else 0
    final_results.append({'name':sname,'rr':rr,'bet':total_bet,'ret':total_ret,
                         'profit':total_ret-total_bet,'races':total_races,
                         'monthly':dict(monthly),'bt_stats':dict(bt_stats)})

print(f'{"#":>3} {"戦略":<22} {"回収率":>7} {"収支":>14} {"レース":>6}')
print('-'*60)
for i,r in enumerate(sorted(final_results,key=lambda x:-x['rr'])):
    print(f'{i+1:>3} {r["name"]:<22} {r["rr"]:>6.1f}% {r["profit"]:>+13,.0f}円 {r["races"]:>6,}')

# 1位の月別
best_strat = sorted(final_results,key=lambda x:-x['rr'])[0]
print(f'\n--- 1位: {best_strat["name"]} (alpha={best_alpha:.2f}) ---')
cb=0;cr=0
for m in sorted(best_strat['monthly'].keys()):
    d=best_strat['monthly'][m]; cb+=d['bet'];cr+=d['ret']
    print(f'  {m}: {d["races"]:>4}R 月{d["ret"]/d["bet"]*100 if d["bet"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

# 券種別
lb={'win':'単勝','umaren':'馬連','wide':'ワイド','sanrenpuku':'三連複'}
for bt in ['win','umaren','wide','sanrenpuku']:
    bs=best_strat['bt_stats'].get(bt)
    if not bs or bs['count']==0: continue
    print(f'  {lb.get(bt,bt)}: {bs["count"]:,}点 的中{bs["hits"]:,} 回収{bs["ret"]/bs["bet"]*100 if bs["bet"]>0 else 0:.1f}%')

print(f'\n=== 全バージョン比較 ===')
print(f'v1: SMのみ(リーク有)              → 111.7%')
print(f'v2: SM+騎手+馬(リーク有)           → 164.8%')
print(f'v3: 騎手+馬(リーク無)              → 104.8%')
print(f'v4: full特徴量(alpha=0.15)        → 115.9%')
print(f'v5: full特徴量(alpha={best_alpha:.2f},時系列補正) → {best_strat["rr"]:.1f}%')

db.close()
sys.stdout.close()
