import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\simulation_2026_v3.txt', 'w', encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

SCALE=0.15; ALPHA=0.2; BETA=1.03; L2=0.8; L3=0.6
EV_TH=1.05; BUDGET=10000; MAX_BETS_PER_RACE=20

CORR = {'win':1.05,'place':1.05,'umaren':1.05,'wide':1.05,'umatan':1.05,'sanrenpuku':1.05,'sanrentan':1.0}
K_MAP = {'win':1,'place':3,'umaren':1,'wide':3,'umatan':1,'sanrenpuku':1,'sanrentan':1}
AQ = {'win':0.2,'place':0.2,'umaren':0.2,'wide':0.2,'umatan':0.2,'sanrenpuku':0.15,'sanrentan':0.1}

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

def c2(pr,w,c):
    r=sum(p**L2 for i,p in enumerate(pr) if i!=w); return pr[c]**L2/r if r>0 else 0
def c3(pr,f,s,c):
    r=sum(p**L3 for i,p in enumerate(pr) if i!=f and i!=s); return pr[c]**L3/r if r>0 else 0

def harv(bt,pr,idx):
    if bt=='win': return pr[idx[0]]
    elif bt=='umaren': return pr[idx[0]]*c2(pr,idx[0],idx[1])+pr[idx[1]]*c2(pr,idx[1],idx[0])
    elif bt=='umatan': return pr[idx[0]]*c2(pr,idx[0],idx[1])
    elif bt=='sanrenpuku':
        pm=[[idx[0],idx[1],idx[2]],[idx[0],idx[2],idx[1]],[idx[1],idx[0],idx[2]],[idx[1],idx[2],idx[0]],[idx[2],idx[0],idx[1]],[idx[2],idx[1],idx[0]]]
        return sum(pr[i]*c2(pr,i,j)*c3(pr,i,j,k) for i,j,k in pm)
    elif bt=='sanrentan': return pr[idx[0]]*c2(pr,idx[0],idx[1])*c3(pr,idx[0],idx[1],idx[2])
    return 0

def check_hit(bt, parts, top3):
    if bt=='win': return parts[0]==top3[0]
    elif bt=='place': return parts[0] in top3
    elif bt=='umaren': return set(parts)==set(top3[:2])
    elif bt=='wide': return parts[0] in top3 and parts[1] in top3
    elif bt=='umatan': return parts[0]==top3[0] and parts[1]==top3[1]
    elif bt=='sanrenpuku': return set(parts)==set(top3[:3])
    elif bt=='sanrentan': return list(parts)==list(top3[:3])
    return False

races = db.execute("SELECT race_id,race_date FROM races WHERE race_date LIKE '2026-%' ORDER BY race_date").fetchall()
print(f'2026 races: {len(races)}')

stats = defaultdict(lambda:{'bet':0,'ret':0,'hits':0,'count':0})
monthly = defaultdict(lambda:{'bet':0,'ret':0,'races':0,'bets':0})
total_bet=0; total_return=0; total_races=0

for ri,(race_id,race_date) in enumerate(races):
    res = db.execute("SELECT horse_number,finish_position,win_odds FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position",(race_id,)).fetchall()
    if len(res)<5: continue
    top3_hn=[r[0] for r in res if r[1]<=3]
    if len(top3_hn)<3: continue

    oz_win=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(race_id,)).fetchall()
    if not oz_win: continue
    oz_map={int(r[0]):r[1] for r in oz_win}
    fin_map={r[0]:r[2] for r in res if r[2] and r[2]>0}

    hl=sorted(set(oz_map.keys())&set(fin_map.keys()))
    if len(hl)<5: continue

    early=[oz_map[h] for h in hl]; final=[fin_map[h] for h in hl]
    eI=[1/o for o in early]; eS=sum(eI)
    fI=[1/o for o in final]; fS=sum(fI)
    scores=[50+math.log(max((fI[i]/fS)/(eI[i]/eS),0.01))*10 for i in range(len(hl))]

    mp=softmax(scores); mkp=mktp(early); bp=blendf(mp,mkp)

    all_ev_bets=[]
    month=race_date[:7]

    for bt in ['win','umaren','umatan','sanrenpuku','sanrentan']:
        oz_rows=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type=?",(race_id,bt)).fetchall()
        if not oz_rows: continue
        K=K_MAP.get(bt,1); corr=CORR.get(bt,1.0); aq=AQ.get(bt,0.2)
        pI=sum(1/r[1] for r in oz_rows if r[1]>0)
        if pI==0: continue

        raws=[]
        for cs,oo in oz_rows:
            if oo<=0: continue
            parts=[int(x) for x in cs.split('-')]
            idx=[]
            ok=True
            for p in parts:
                if p in hl: idx.append(hl.index(p))
                else: ok=False; break
            if not ok: continue
            qm=harv(bt,bp,idx)
            if qm<=0: continue
            piP=K*(1/oo)/pI
            if piP<=0: continue
            lnQ=aq*math.log(qm)+(1-aq)*math.log(piP)
            raws.append((cs,oo,parts,lnQ))

        if not raws: continue
        mxL=max(r[3] for r in raws); exS=sum(math.exp(r[3]-mxL) for r in raws)

        for cs,oo,parts,lnQ in raws:
            qF=K*math.exp(lnQ-mxL)/exS
            co=oo*corr; ev=qF*co
            if ev>=EV_TH:
                ky=max(0,(qF*co-1)/(co-1))/4
                hit=check_hit(bt,parts,top3_hn[:3])
                all_ev_bets.append({'bt':bt,'combo':cs,'ev':ev,'kelly':ky,'odds':co,'hit':hit,'parts':parts})

    if not all_ev_bets: continue

    # EV高い順にソートして上位MAX_BETS_PER_RACE点に絞る
    all_ev_bets.sort(key=lambda x: -x['ev'])
    all_ev_bets = all_ev_bets[:MAX_BETS_PER_RACE]

    # ケリー配分（予算厳守）
    tK=sum(b['kelly'] for b in all_ev_bets)
    if tK<=0: continue

    # 各買い目の生額を計算
    raw_amounts = [(b, BUDGET * b['kelly']) for b in all_ev_bets]
    raw_total = sum(a for _, a in raw_amounts)

    # 予算超過なら比例縮小、未満ならそのまま（スケールアップしない）
    scale = min(1.0, BUDGET / raw_total) if raw_total > 0 else 1.0

    rb=0; rr=0
    for b, raw_amt in raw_amounts:
        amt = max(100, round(raw_amt * scale / 100) * 100)
        # 予算オーバーしないようにチェック
        if rb + amt > BUDGET:
            amt = max(0, BUDGET - rb)
            amt = (amt // 100) * 100
        if amt <= 0: continue

        rb += amt
        stats[b['bt']]['count'] += 1
        stats[b['bt']]['bet'] += amt
        if b['hit']:
            ret = amt * b['odds']
            rr += ret
            stats[b['bt']]['hits'] += 1
            stats[b['bt']]['ret'] += ret

    if rb == 0: continue
    total_bet += rb; total_return += rr; total_races += 1
    monthly[month]['bet'] += rb; monthly[month]['ret'] += rr
    monthly[month]['races'] += 1; monthly[month]['bets'] += len(all_ev_bets)

print(f'\n=== 2026年 全券種シミュレーション（予算{BUDGET:,}円/レース厳守） ===')
print(f'対象レース: {total_races}')
print(f'総投資: {total_bet:>12,.0f}円')
print(f'総払戻: {total_return:>12,.0f}円')
print(f'収支:   {total_return-total_bet:>+12,.0f}円')
if total_bet>0: print(f'回収率: {total_return/total_bet*100:.1f}%')
print(f'1レース平均投資: {total_bet/total_races:,.0f}円' if total_races>0 else '')

print(f'\n=== 券種別 ===')
print(f'{"券種":<10} {"点数":>7} {"的中":>5} {"的中率":>7} {"投資":>12} {"払戻":>12} {"回収率":>7}')
print('-'*65)
lb={'win':'単勝','place':'複勝','umaren':'馬連','wide':'ワイド','umatan':'馬単','sanrenpuku':'三連複','sanrentan':'三連単'}
for bt in ['win','place','umaren','wide','umatan','sanrenpuku','sanrentan']:
    s=stats[bt]
    if s['count']==0: continue
    print(f'{lb.get(bt,bt):<10} {s["count"]:>7,} {s["hits"]:>5,} {s["hits"]/s["count"]*100:>6.1f}% {s["bet"]:>11,.0f}円 {s["ret"]:>11,.0f}円 {s["ret"]/s["bet"]*100 if s["bet"]>0 else 0:>6.1f}%')

print(f'\n=== 月別 ===')
cb=0;cr=0
for m in sorted(monthly.keys()):
    d=monthly[m]; cb+=d['bet']; cr+=d['ret']
    avg_bets = d['bets']/d['races'] if d['races']>0 else 0
    print(f'{m}: {d["races"]:>4}R 平均{avg_bets:.1f}点 投資{d["bet"]:>9,.0f}円 払戻{d["ret"]:>9,.0f}円 月回収{d["ret"]/d["bet"]*100 if d["bet"]>0 else 0:>6.1f}% 累積{cr/cb*100 if cb>0 else 0:>6.1f}% 損益{cr-cb:>+10,.0f}円')

db.close()
sys.stdout.close()
