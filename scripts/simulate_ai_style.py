"""
AI推奨買い目スタイルのシミュレーション
EV閾値なし、上位馬の組み合わせを予算10,000円/レースで購入
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\simulation_ai_style.txt', 'w', encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

SCALE=0.15; ALPHA=0.2; BETA=1.03; L2=0.8; BUDGET=10000
CORR = {'win':1.05,'umaren':1.05,'wide':1.05,'umatan':1.05,'sanrenpuku':1.05,'sanrentan':1.0}

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

def check_hit(bt, parts, top3):
    if bt=='win': return parts[0]==top3[0]
    elif bt=='fukusho': return parts[0] in top3
    elif bt=='umaren': return set(parts)==set(top3[:2])
    elif bt=='wide': return parts[0] in top3 and parts[1] in top3
    elif bt=='umatan': return parts[0]==top3[0] and parts[1]==top3[1]
    elif bt=='sanrenpuku': return set(parts)==set(top3[:3])
    elif bt=='sanrentan': return list(parts)==list(top3[:3])
    return False

# データロード
races = db.execute("SELECT race_id,race_date FROM races WHERE race_date LIKE '2026-%' ORDER BY race_date").fetchall()

race_cache = {}
for race_id, race_date in races:
    res = db.execute("SELECT horse_number,finish_position,win_odds FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position",(race_id,)).fetchall()
    if len(res)<5: continue
    top3=[r[0] for r in res if r[1]<=3]
    if len(top3)<3: continue
    oz_win=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(race_id,)).fetchall()
    if not oz_win: continue
    oz_map={int(r[0]):r[1] for r in oz_win}
    fin_map={r[0]:r[2] for r in res if r[2] and r[2]>0}
    hl=sorted(set(oz_map.keys())&set(fin_map.keys()))
    if len(hl)<5: continue

    odds_data={}
    for bt in ['win','umaren','umatan','wide','sanrenpuku','sanrentan']:
        rows=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type=?",(race_id,bt)).fetchall()
        if rows: odds_data[bt]={r[0]:r[1] for r in rows}

    race_cache[race_id]={
        'date':race_date,'top3':top3[:3],'hl':hl,
        'early':[oz_map[h] for h in hl],'final':[fin_map[h] for h in hl],
        'odds_data':odds_data,
    }

print(f'Cached {len(race_cache)} races')
db.close()

# 買い方パターン定義
# top = blended確率順の上位馬番（1-indexed）
strategies = {
    'S01: 単勝◎のみ': lambda top, od: [
        ('win', [top[0]], 10000),
    ],
    'S02: 複勝◎のみ': lambda top, od: [
        ('fukusho', [top[0]], 10000),
    ],
    'S03: 単勝◎+複勝◎': lambda top, od: [
        ('win', [top[0]], 5000),
        ('fukusho', [top[0]], 5000),
    ],
    'S04: 馬連◎○▲ 3点': lambda top, od: [
        ('umaren', sorted([top[0],top[1]]), 3300),
        ('umaren', sorted([top[0],top[2]]), 3300),
        ('umaren', sorted([top[1],top[2]]), 3400),
    ],
    'S05: ワイド◎○▲ 3点': lambda top, od: [
        ('wide', sorted([top[0],top[1]]), 3300),
        ('wide', sorted([top[0],top[2]]), 3300),
        ('wide', sorted([top[1],top[2]]), 3400),
    ],
    'S06: 三連複◎○▲ 1点': lambda top, od: [
        ('sanrenpuku', sorted([top[0],top[1],top[2]]), 10000),
    ],
    'S07: 三連複◎○▲△ 4点': lambda top, od: [
        ('sanrenpuku', sorted([top[0],top[1],top[2]]), 4000),
        ('sanrenpuku', sorted([top[0],top[1],top[3]]), 2000),
        ('sanrenpuku', sorted([top[0],top[2],top[3]]), 2000),
        ('sanrenpuku', sorted([top[1],top[2],top[3]]), 2000),
    ],
    'S08: 馬単◎→○,◎→▲': lambda top, od: [
        ('umatan', [top[0],top[1]], 5000),
        ('umatan', [top[0],top[2]], 5000),
    ],
    'S09: 三連単◎→○→▲ 他': lambda top, od: [
        ('sanrentan', [top[0],top[1],top[2]], 3000),
        ('sanrentan', [top[0],top[2],top[1]], 2000),
        ('sanrentan', [top[1],top[0],top[2]], 2000),
        ('sanrentan', [top[2],top[0],top[1]], 1500),
        ('sanrentan', [top[1],top[2],top[0]], 1500),
    ],
    'S10: MIX 単複馬連三複': lambda top, od: [
        ('win', [top[0]], 2000),
        ('fukusho', [top[0]], 1000),
        ('umaren', sorted([top[0],top[1]]), 2000),
        ('umaren', sorted([top[0],top[2]]), 1500),
        ('sanrenpuku', sorted([top[0],top[1],top[2]]), 2000),
        ('wide', sorted([top[0],top[1]]), 1500),
    ],
    'S11: MIX 全券種': lambda top, od: [
        ('win', [top[0]], 1000),
        ('umaren', sorted([top[0],top[1]]), 1500),
        ('umaren', sorted([top[0],top[2]]), 1000),
        ('wide', sorted([top[0],top[1]]), 1000),
        ('umatan', [top[0],top[1]], 1500),
        ('sanrenpuku', sorted([top[0],top[1],top[2]]), 2000),
        ('sanrentan', [top[0],top[1],top[2]], 2000),
    ],
    'S12: 単勝◎○ 2点': lambda top, od: [
        ('win', [top[0]], 6000),
        ('win', [top[1]], 4000),
    ],
    'S13: ワイド◎○▲△ 6点': lambda top, od: [
        ('wide', sorted([top[0],top[1]]), 2500),
        ('wide', sorted([top[0],top[2]]), 2000),
        ('wide', sorted([top[0],top[3]]), 1500),
        ('wide', sorted([top[1],top[2]]), 1500),
        ('wide', sorted([top[1],top[3]]), 1500),
        ('wide', sorted([top[2],top[3]]), 1000),
    ],
    'S14: 馬連◎流し5点': lambda top, od: [
        ('umaren', sorted([top[0],top[1]]), 3000),
        ('umaren', sorted([top[0],top[2]]), 2500),
        ('umaren', sorted([top[0],top[3]]), 2000),
        ('umaren', sorted([top[0],top[4]]), 1500),
        ('umaren', sorted([top[0],top[5]]), 1000),
    ] if len(top)>=6 else [],
}

results = []

for sname, sfn in strategies.items():
    total_bet=0; total_ret=0; total_races=0; total_hits=0; total_bets=0
    monthly=defaultdict(lambda:{'bet':0,'ret':0,'races':0,'hits':0})
    bt_stats=defaultdict(lambda:{'bet':0,'ret':0,'hits':0,'count':0})

    for race_id, rc in race_cache.items():
        hl=rc['hl']; early=rc['early']; final=rc['final']; top3=rc['top3']
        od=rc['odds_data']

        eI=[1/o for o in early]; eS=sum(eI)
        fI=[1/o for o in final]; fS=sum(fI)
        scores=[50+math.log(max((fI[i]/fS)/(eI[i]/eS),0.01))*10 for i in range(len(hl))]
        mp=softmax(scores); mkp=mktp(early); bp=blendf(mp,mkp)

        # 上位6頭（馬番、blended確率順）
        ranked=sorted(range(len(hl)), key=lambda i: -bp[i])
        top_hn=[hl[r] for r in ranked[:min(6,len(ranked))]]

        if len(top_hn)<4: continue

        bets=sfn(top_hn, od)
        if not bets: continue

        month=rc['date'][:7]
        rb=0; rr=0; r_hits=0

        for bt, parts, amount in bets:
            combo_key='-'.join(str(p) for p in parts)

            # OZオッズを取得
            if bt=='fukusho':
                db_bt='place'; lookup_key=str(parts[0])
            elif bt=='win':
                db_bt='win'; lookup_key=str(parts[0])
            else:
                db_bt=bt; lookup_key=combo_key

            if db_bt not in od: continue
            oz_odds=od[db_bt].get(lookup_key, 0)
            if oz_odds<=0: continue

            corr=CORR.get(db_bt, 1.0)
            payout_odds=oz_odds*corr

            hit=check_hit(bt, parts, top3)
            rb+=amount; total_bets+=1
            bt_stats[bt]['count']+=1; bt_stats[bt]['bet']+=amount

            if hit:
                ret=amount*payout_odds
                rr+=ret; r_hits+=1; total_hits+=1
                bt_stats[bt]['hits']+=1; bt_stats[bt]['ret']+=ret

        if rb==0: continue
        total_bet+=rb; total_ret+=rr; total_races+=1
        monthly[month]['bet']+=rb; monthly[month]['ret']+=rr
        monthly[month]['races']+=1; monthly[month]['hits']+=r_hits

    rr_pct=total_ret/total_bet*100 if total_bet>0 else 0
    hit_pct=total_hits/total_bets*100 if total_bets>0 else 0

    results.append({
        'name':sname,'races':total_races,'bets':total_bets,
        'hits':total_hits,'hit_pct':hit_pct,
        'bet':total_bet,'ret':total_ret,
        'profit':total_ret-total_bet,'rr':rr_pct,
        'monthly':dict(monthly),'bt_stats':dict(bt_stats),
    })

# ランキング出力
print('\n' + '='*110)
print('=== AI推奨スタイル シミュレーション結果（2026年、10,000円/レース） ===')
print('='*110)
print(f'{"#":>3} {"戦略":<30} {"レース":>6} {"点数":>7} {"的中":>5} {"的中率":>7} {"総投資":>14} {"総払戻":>14} {"収支":>14} {"回収率":>7}')
print('-'*115)

for i, r in enumerate(sorted(results, key=lambda x: -x['rr'])):
    print(f'{i+1:>3} {r["name"]:<30} {r["races"]:>6,} {r["bets"]:>7,} {r["hits"]:>5,} {r["hit_pct"]:>6.1f}% {r["bet"]:>13,.0f}円 {r["ret"]:>13,.0f}円 {r["profit"]:>+13,.0f}円 {r["rr"]:>6.1f}%')

# 上位5戦略の詳細
print('\n' + '='*110)
print('=== 上位5戦略の詳細 ===')
print('='*110)

for i, r in enumerate(sorted(results, key=lambda x: -x['rr'])[:5]):
    print(f'\n--- {i+1}位: {r["name"]} ---')
    print(f'  回収率: {r["rr"]:.1f}% | 的中: {r["hits"]}/{r["bets"]}点 ({r["hit_pct"]:.1f}%) | 損益: {r["profit"]:+,.0f}円')

    # 券種別
    print(f'  券種別:')
    lb={'win':'単勝','fukusho':'複勝','umaren':'馬連','wide':'ワイド','umatan':'馬単','sanrenpuku':'三連複','sanrentan':'三連単'}
    for bt in ['win','fukusho','umaren','wide','umatan','sanrenpuku','sanrentan']:
        bs=r['bt_stats'].get(bt)
        if not bs or bs['count']==0: continue
        print(f'    {lb.get(bt,bt)}: {bs["count"]:,}点 的中{bs["hits"]:,} 投資{bs["bet"]:,.0f}円 払戻{bs["ret"]:,.0f}円 回収{bs["ret"]/bs["bet"]*100 if bs["bet"]>0 else 0:.1f}%')

    # 月別
    print(f'  月別:')
    cb=0;cr=0
    for m in sorted(r['monthly'].keys()):
        d=r['monthly'][m]; cb+=d['bet']; cr+=d['ret']
        print(f'    {m}: {d["races"]:>4}R 投資{d["bet"]:>9,.0f}円 払戻{d["ret"]:>9,.0f}円 月{d["ret"]/d["bet"]*100 if d["bet"]>0 else 0:>6.1f}% 累積{cr/cb*100 if cb>0 else 0:>6.1f}% 損益{cr-cb:>+10,.0f}円')

sys.stdout.close()
