"""
モデルパラメータ最適化シミュレーション
2026年の全レースで各パラメータセットの収支を比較
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\model_ranking.txt', 'w', encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

BETA = 1.03; L2 = 0.8; L3 = 0.6; BUDGET = 10000

def softmax(sc, scale):
    s = [(x-50)*scale for x in sc]; mx = max(s) if s else 0
    e = [math.exp(x-mx) for x in s]; t = sum(e)
    return [x/t for x in e] if t > 0 else []

def mktp(odds):
    inv = [1/o if o > 0 else 0 for o in odds]; s = sum(inv)
    if s == 0: return [1/len(odds)]*len(odds)
    raw = [i/s for i in inv]; pw = [p**BETA for p in raw]; ps = sum(pw)
    return [p/ps for p in pw]

def blendf(m, mk, alpha):
    bl = [math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s = sum(bl); return [p/s for p in bl] if s > 0 else bl

def c2(pr,w,c):
    r = sum(p**L2 for i,p in enumerate(pr) if i!=w); return pr[c]**L2/r if r > 0 else 0

def c3(pr,f,s,c):
    r = sum(p**L3 for i,p in enumerate(pr) if i!=f and i!=s); return pr[c]**L3/r if r > 0 else 0

def harv(bt, pr, idx):
    if bt == 'win': return pr[idx[0]]
    elif bt == 'umaren': return pr[idx[0]]*c2(pr,idx[0],idx[1]) + pr[idx[1]]*c2(pr,idx[1],idx[0])
    elif bt == 'umatan': return pr[idx[0]]*c2(pr,idx[0],idx[1])
    elif bt == 'sanrenpuku':
        pm = [[idx[0],idx[1],idx[2]],[idx[0],idx[2],idx[1]],[idx[1],idx[0],idx[2]],[idx[1],idx[2],idx[0]],[idx[2],idx[0],idx[1]],[idx[2],idx[1],idx[0]]]
        return sum(pr[i]*c2(pr,i,j)*c3(pr,i,j,k) for i,j,k in pm)
    elif bt == 'sanrentan': return pr[idx[0]]*c2(pr,idx[0],idx[1])*c3(pr,idx[0],idx[1],idx[2])
    return 0

def check_hit(bt, parts, top3):
    if bt == 'win': return parts[0] == top3[0]
    elif bt == 'umaren': return set(parts) == set(top3[:2])
    elif bt == 'umatan': return parts[0] == top3[0] and parts[1] == top3[1]
    elif bt == 'sanrenpuku': return set(parts) == set(top3[:3])
    elif bt == 'sanrentan': return list(parts) == list(top3[:3])
    return False

# レースデータを事前ロード
print('Loading data...')
races = db.execute("SELECT race_id, race_date FROM races WHERE race_date LIKE '2026-%' ORDER BY race_date").fetchall()

race_cache = {}
for race_id, race_date in races:
    res = db.execute("SELECT horse_number, finish_position, win_odds FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position", (race_id,)).fetchall()
    if len(res) < 5: continue
    top3 = [r[0] for r in res if r[1] <= 3]
    if len(top3) < 3: continue

    oz_win = db.execute("SELECT combination, odds FROM odds WHERE race_id=? AND bet_type='win'", (race_id,)).fetchall()
    if not oz_win: continue
    oz_map = {int(r[0]): r[1] for r in oz_win}
    fin_map = {r[0]: r[2] for r in res if r[2] and r[2] > 0}
    hl = sorted(set(oz_map.keys()) & set(fin_map.keys()))
    if len(hl) < 5: continue

    # オッズデータも事前ロード
    odds_data = {}
    for bt in ['win', 'umaren', 'umatan', 'sanrenpuku', 'sanrentan']:
        rows = db.execute("SELECT combination, odds FROM odds WHERE race_id=? AND bet_type=?", (race_id, bt)).fetchall()
        if rows:
            odds_data[bt] = rows

    race_cache[race_id] = {
        'date': race_date, 'top3': top3[:3], 'hl': hl,
        'early': [oz_map[h] for h in hl],
        'final': [fin_map[h] for h in hl],
        'odds_data': odds_data,
    }

print(f'Cached {len(race_cache)} races\n')
db.close()

# モデル定義
K_MAP = {'win':1, 'umaren':1, 'umatan':1, 'sanrenpuku':1, 'sanrentan':1}

models = [
    # (name, scale, alpha, ev_th, bet_types, corr, max_bets, sm_weight)
    ('M01: 単勝のみ_保守',         0.10, 0.05, 1.03, ['win'], 1.0, 10, 10),
    ('M02: 単勝のみ_標準',         0.15, 0.10, 1.05, ['win'], 1.0, 10, 10),
    ('M03: 単勝のみ_攻め',         0.20, 0.20, 1.05, ['win'], 1.0, 10, 15),
    ('M04: 単勝+馬連_保守',        0.10, 0.05, 1.03, ['win','umaren'], 1.0, 10, 10),
    ('M05: 単勝+馬連_標準',        0.15, 0.10, 1.05, ['win','umaren'], 1.0, 10, 10),
    ('M06: 単勝+馬連_攻め',        0.20, 0.20, 1.05, ['win','umaren'], 1.0, 10, 15),
    ('M07: 単馬馬単_保守',         0.10, 0.05, 1.03, ['win','umaren','umatan'], 1.0, 15, 10),
    ('M08: 単馬馬単_標準',         0.15, 0.10, 1.05, ['win','umaren','umatan'], 1.0, 15, 10),
    ('M09: 全券種_保守',           0.10, 0.05, 1.03, ['win','umaren','umatan','sanrenpuku','sanrentan'], 1.0, 20, 10),
    ('M10: 全券種_標準',           0.15, 0.10, 1.05, ['win','umaren','umatan','sanrenpuku','sanrentan'], 1.0, 20, 10),
    ('M11: 全券種_攻め',           0.20, 0.20, 1.05, ['win','umaren','umatan','sanrenpuku','sanrentan'], 1.0, 20, 15),
    ('M12: 単勝_低alpha',          0.15, 0.03, 1.02, ['win'], 1.0, 10, 10),
    ('M13: 単勝_高SM',             0.15, 0.10, 1.05, ['win'], 1.0, 10, 25),
    ('M14: 単勝_高scale',          0.25, 0.10, 1.05, ['win'], 1.0, 10, 10),
    ('M15: 馬連_低alpha',          0.15, 0.03, 1.02, ['umaren'], 1.0, 10, 10),
    ('M16: 馬連のみ_標準',         0.15, 0.10, 1.05, ['umaren'], 1.0, 10, 10),
    ('M17: 馬単のみ_標準',         0.15, 0.10, 1.05, ['umatan'], 1.0, 15, 10),
    ('M18: 三連複のみ_標準',       0.15, 0.10, 1.05, ['sanrenpuku'], 1.0, 15, 10),
    ('M19: 単勝_補正あり',         0.15, 0.10, 1.05, ['win'], 1.05, 10, 10),
    ('M20: 全券種_補正あり',       0.15, 0.10, 1.05, ['win','umaren','umatan','sanrenpuku','sanrentan'], 1.05, 20, 10),
    ('M21: 単勝_EV1.00以上',       0.15, 0.10, 1.00, ['win'], 1.0, 10, 10),
    ('M22: 単勝+馬連_EV1.00',      0.15, 0.10, 1.00, ['win','umaren'], 1.0, 10, 10),
    ('M23: 全券種_EV1.00_低alpha', 0.10, 0.03, 1.00, ['win','umaren','umatan','sanrenpuku'], 1.0, 20, 10),
    ('M24: 単勝_SM重視',           0.15, 0.15, 1.05, ['win'], 1.0, 10, 30),
]

results = []

for mi, (name, scale, alpha, ev_th, bet_types, corr, max_bets, sm_w) in enumerate(models):
    total_bet = 0; total_ret = 0; total_hits = 0; total_bets = 0; total_races = 0
    monthly_profits = []

    for race_id, rc in race_cache.items():
        hl = rc['hl']; early = rc['early']; final = rc['final']
        top3 = rc['top3']

        eI = [1/o for o in early]; eS = sum(eI)
        fI = [1/o for o in final]; fS = sum(fI)
        scores = [50 + math.log(max((fI[i]/fS)/(eI[i]/eS), 0.01)) * sm_w for i in range(len(hl))]

        mp = softmax(scores, scale)
        mkp = mktp(early)
        bp = blendf(mp, mkp, alpha)

        race_ev_bets = []

        for bt in bet_types:
            if bt not in rc['odds_data']: continue
            oz_rows = rc['odds_data'][bt]
            K = K_MAP.get(bt, 1)
            aq = {'win':alpha,'umaren':0.2,'umatan':0.2,'sanrenpuku':0.15,'sanrentan':0.1}.get(bt, 0.2)
            pI = sum(1/r[1] for r in oz_rows if r[1] > 0)
            if pI == 0: continue

            raws = []
            for cs, oo in oz_rows:
                if oo <= 0: continue
                parts = [int(x) for x in cs.split('-')]
                idx = []
                ok = True
                for p in parts:
                    if p in hl: idx.append(hl.index(p))
                    else: ok = False; break
                if not ok: continue
                qm = harv(bt, bp, idx)
                if qm <= 0: continue
                piP = K*(1/oo)/pI
                if piP <= 0: continue
                lnQ = aq*math.log(qm) + (1-aq)*math.log(piP)
                raws.append((cs, oo, parts, lnQ))

            if not raws: continue
            mxL = max(r[3] for r in raws)
            exS = sum(math.exp(r[3]-mxL) for r in raws)

            for cs, oo, parts, lnQ in raws:
                qF = K*math.exp(lnQ-mxL)/exS
                co = oo*corr; ev = qF*co
                if ev >= ev_th:
                    ky = max(0, (qF*co-1)/(co-1))/4
                    hit = check_hit(bt, parts, top3)
                    race_ev_bets.append({'ev':ev, 'kelly':ky, 'odds':co, 'hit':hit})

        if not race_ev_bets: continue

        race_ev_bets.sort(key=lambda x: -x['ev'])
        race_ev_bets = race_ev_bets[:max_bets]

        tK = sum(b['kelly'] for b in race_ev_bets)
        if tK <= 0: continue
        rawT = sum(BUDGET*b['kelly'] for b in race_ev_bets)
        sc = min(1.0, BUDGET/rawT) if rawT > 0 else 1.0

        rb = 0; rr = 0
        for b in race_ev_bets:
            amt = max(100, round(BUDGET*b['kelly']*sc/100)*100)
            if rb + amt > BUDGET:
                amt = ((BUDGET - rb)//100)*100
            if amt <= 0: continue
            rb += amt; total_bets += 1
            if b['hit']:
                ret = amt*b['odds']; rr += ret; total_hits += 1

        if rb == 0: continue
        total_bet += rb; total_ret += rr; total_races += 1

    rr_pct = total_ret/total_bet*100 if total_bet > 0 else 0
    hit_pct = total_hits/total_bets*100 if total_bets > 0 else 0
    avg_bet = total_bet/total_races if total_races > 0 else 0

    results.append({
        'name': name, 'races': total_races, 'bets': total_bets,
        'hits': total_hits, 'hit_pct': hit_pct,
        'bet': total_bet, 'ret': total_ret,
        'profit': total_ret - total_bet, 'rr': rr_pct, 'avg_bet': avg_bet,
    })
    print(f'  {name}: {total_races}R {total_bets}点 的中{total_hits} 投資{total_bet:,}円 払戻{total_ret:,}円 回収{rr_pct:.1f}%')

# ランキング出力
print('\n' + '='*100)
print('=== モデルランキング（回収率順） ===')
print('='*100)
print(f'{"#":>3} {"モデル":<28} {"レース":>6} {"点数":>7} {"的中":>5} {"的中率":>7} {"投資":>12} {"払戻":>12} {"収支":>12} {"回収率":>7}')
print('-'*105)

for i, r in enumerate(sorted(results, key=lambda x: -x['rr'])):
    print(f'{i+1:>3} {r["name"]:<28} {r["races"]:>6} {r["bets"]:>7,} {r["hits"]:>5} {r["hit_pct"]:>6.1f}% {r["bet"]:>11,.0f}円 {r["ret"]:>11,.0f}円 {r["profit"]:>+11,.0f}円 {r["rr"]:>6.1f}%')

# 的中数順
print('\n' + '='*100)
print('=== モデルランキング（的中数順） ===')
print('='*100)
for i, r in enumerate(sorted(results, key=lambda x: -x['hits'])):
    print(f'{i+1:>3} {r["name"]:<28} 的中{r["hits"]:>5} / {r["bets"]:>7,}点 ({r["hit_pct"]:.1f}%) 回収{r["rr"]:.1f}%')

# 安定性評価（大当たり1回に依存しないモデル）
print('\n' + '='*100)
print('=== 安定性評価（的中5回以上 & 回収率順） ===')
print('='*100)
stable = [r for r in results if r['hits'] >= 5]
for i, r in enumerate(sorted(stable, key=lambda x: -x['rr'])):
    print(f'{i+1:>3} {r["name"]:<28} 的中{r["hits"]:>5} 回収{r["rr"]:.1f}% 投資{r["bet"]:,.0f}円 損益{r["profit"]:+,.0f}円')

sys.stdout.close()
