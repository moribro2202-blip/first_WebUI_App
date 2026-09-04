"""
AIスコア疑似モデルのシミュレーション
スマートマネー + 過去成績 + 騎手勝率 をスコアに組み込む
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\simulation_ai_score.txt', 'w', encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

BETA=1.03; L2=0.8; BUDGET=10000

# 騎手勝率をキャッシュ
jockey_stats = {}
rows = db.execute('''
    SELECT jockey_name, COUNT(*) as total,
           SUM(CASE WHEN finish_position=1 THEN 1 ELSE 0 END) as wins
    FROM results WHERE jockey_name IS NOT NULL AND jockey_name != ''
    GROUP BY jockey_name HAVING total >= 20
''').fetchall()
for name, total, wins in rows:
    jockey_stats[name] = wins/total if total > 0 else 0

# 馬の過去成績キャッシュ（直近5走の平均着順）
horse_avg = {}
rows = db.execute('''
    SELECT horse_id, AVG(finish_position) as avg_pos, COUNT(*) as cnt
    FROM (
        SELECT horse_id, finish_position,
               ROW_NUMBER() OVER (PARTITION BY horse_id ORDER BY race_id DESC) as rn
        FROM results WHERE horse_id IS NOT NULL AND finish_position IS NOT NULL
    ) WHERE rn <= 5
    GROUP BY horse_id HAVING cnt >= 2
''').fetchall()
for hid, avg, cnt in rows:
    horse_avg[hid] = avg

print(f'Jockey stats: {len(jockey_stats)}, Horse avg: {len(horse_avg)}')

CORR = 1.05

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

def c2(pr,w,c):
    r=sum(p**L2 for i,p in enumerate(pr) if i!=w); return pr[c]**L2/r if r>0 else 0

def trio_prob(pr,a,b,c):
    pm=[[a,b,c],[a,c,b],[b,a,c],[b,c,a],[c,a,b],[c,b,a]]
    L3=0.6
    def c3(f,s,cc):
        r=sum(p**L3 for i,p in enumerate(pr) if i!=f and i!=s); return pr[cc]**L3/r if r>0 else 0
    return sum(pr[i]*c2(pr,i,j)*c3(i,j,k) for i,j,k in pm)

# レースデータ取得
races = db.execute("SELECT race_id,race_date FROM races WHERE race_date LIKE '2026-%' ORDER BY race_date").fetchall()

# エントリー情報取得
entry_cache = {}
for race_id, _ in races:
    entries = db.execute('''
        SELECT e.horse_number, e.horse_id, e.jockey_name, e.horse_name
        FROM entries e WHERE e.race_id = ?
    ''', (race_id,)).fetchall()
    if entries:
        entry_cache[race_id] = {e[0]: {'hid': e[1], 'jockey': e[2], 'name': e[3]} for e in entries}

# モデル定義
models = [
    # (name, scale, alpha, score_fn_name)
    ('A: SMのみ(v1ベースライン)',          0.15, 0.20, 'sm_only'),
    ('B: SM+騎手勝率',                    0.15, 0.20, 'sm_jockey'),
    ('C: SM+馬過去成績',                  0.15, 0.20, 'sm_horse'),
    ('D: SM+騎手+馬成績',                 0.15, 0.20, 'sm_jockey_horse'),
    ('E: SM+騎手+馬_alpha0.10',           0.15, 0.10, 'sm_jockey_horse'),
    ('F: SM+騎手+馬_alpha0.30',           0.15, 0.30, 'sm_jockey_horse'),
    ('G: SM+騎手+馬_scale0.10',           0.10, 0.20, 'sm_jockey_horse'),
    ('H: SM+騎手+馬_scale0.20',           0.20, 0.20, 'sm_jockey_horse'),
    ('I: 騎手+馬のみ(SMなし)',             0.15, 0.20, 'jockey_horse_only'),
    ('J: 市場のみ(alpha=0)',              0.15, 0.00, 'sm_only'),
    ('K: SM+騎手+馬_alpha0.05',           0.15, 0.05, 'sm_jockey_horse'),
    ('L: SM重視+騎手+馬',                 0.15, 0.20, 'sm_heavy_jockey_horse'),
]

def calc_scores(fn_name, hl, early, final, race_id):
    eI=[1/o for o in early]; eS=sum(eI)
    fI=[1/o for o in final]; fS=sum(fI)

    scores = []
    for i, h in enumerate(hl):
        base = 50.0

        # スマートマネー
        sm = math.log(max((fI[i]/fS)/(eI[i]/eS), 0.01)) * 10

        # 騎手勝率ボーナス
        jockey_bonus = 0
        entry = entry_cache.get(race_id, {}).get(h, {})
        jname = entry.get('jockey', '')
        if jname and jname in jockey_stats:
            jr = jockey_stats[jname]
            jockey_bonus = (jr - 0.08) * 50  # 平均8%基準、勝率15%なら+3.5

        # 馬の過去成績ボーナス
        horse_bonus = 0
        hid = entry.get('hid', '')
        if hid and hid in horse_avg:
            avg = horse_avg[hid]
            horse_bonus = (6 - avg) * 2  # 平均着順6基準、3着なら+6

        if fn_name == 'sm_only':
            scores.append(base + sm)
        elif fn_name == 'sm_jockey':
            scores.append(base + sm + jockey_bonus)
        elif fn_name == 'sm_horse':
            scores.append(base + sm + horse_bonus)
        elif fn_name == 'sm_jockey_horse':
            scores.append(base + sm + jockey_bonus + horse_bonus)
        elif fn_name == 'jockey_horse_only':
            scores.append(base + jockey_bonus + horse_bonus)
        elif fn_name == 'sm_heavy_jockey_horse':
            scores.append(base + sm * 2 + jockey_bonus + horse_bonus)
        else:
            scores.append(base + sm)

    return scores

# 三連複◎○▲ 1点 戦略でシミュレーション
print('=== 三連複◎○▲ 1点 戦略 シミュレーション ===\n')

all_results = []

for mname, scale, alpha, score_fn in models:
    total_bet=0; total_ret=0; total_races=0; total_hits=0
    monthly=defaultdict(lambda:{'bet':0,'ret':0,'races':0})

    for race_id, race_date in races:
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

        scores = calc_scores(score_fn, hl, early, final, race_id)
        mp = softmax(scores, scale)
        mkp = mktp(early)
        bp = blendf(mp, mkp, alpha)

        ranked = sorted(range(len(hl)), key=lambda i: -bp[i])
        top_hn = [hl[r] for r in ranked[:3]]

        # 三連複オッズ取得
        combo = '-'.join(str(h) for h in sorted(top_hn))
        oz_row = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(race_id,combo)).fetchone()
        if not oz_row or oz_row[0] <= 0: continue

        odds = oz_row[0] * CORR
        hit = set(top_hn) == set(top3_hn[:3])

        total_bet += BUDGET; total_races += 1
        month = race_date[:7]
        monthly[month]['bet'] += BUDGET; monthly[month]['races'] += 1

        if hit:
            ret = BUDGET * odds
            total_ret += ret; total_hits += 1
            monthly[month]['ret'] += ret

    rr = total_ret/total_bet*100 if total_bet>0 else 0
    hr = total_hits/total_races*100 if total_races>0 else 0

    all_results.append({
        'name':mname,'races':total_races,'hits':total_hits,'hit_pct':hr,
        'bet':total_bet,'ret':total_ret,'profit':total_ret-total_bet,'rr':rr,
        'monthly':dict(monthly),
    })

# ランキング
print(f'{"#":>3} {"モデル":<35} {"レース":>6} {"的中":>5} {"的中率":>7} {"投資":>14} {"払戻":>14} {"収支":>14} {"回収率":>7}')
print('-'*115)
for i, r in enumerate(sorted(all_results, key=lambda x: -x['rr'])):
    print(f'{i+1:>3} {r["name"]:<35} {r["races"]:>6,} {r["hits"]:>5} {r["hit_pct"]:>6.1f}% {r["bet"]:>13,.0f}円 {r["ret"]:>13,.0f}円 {r["profit"]:>+13,.0f}円 {r["rr"]:>6.1f}%')

# 上位3の月別
print('\n=== 上位3モデルの月別推移 ===')
for i, r in enumerate(sorted(all_results, key=lambda x: -x['rr'])[:3]):
    print(f'\n--- {i+1}位: {r["name"]} (回収率{r["rr"]:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(r['monthly'].keys()):
        d=r['monthly'][m]; cb+=d['bet']; cr+=d['ret']
        print(f'  {m}: {d["races"]:>4}R 月{d["ret"]/d["bet"]*100 if d["bet"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

db.close()
sys.stdout.close()
