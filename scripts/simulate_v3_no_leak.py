"""
v3: 未来データリーク排除シミュレーション
- スマートマネー信号なし（確定オッズはレース前に不明）
- 馬の過去成績はそのレースより前のデータのみ
- 騎手勝率もそのレース時点までの累積
- 三連複◎○▲ 1点戦略
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\simulation_v3_no_leak.txt', 'w', encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

BETA=1.03; L2=0.8; L3=0.6; BUDGET=10000; CORR=1.05

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

# 全レースを時系列順に取得
races = db.execute('''
    SELECT r.race_id, r.race_date, r.venue_name, r.race_number
    FROM races r ORDER BY r.race_date, r.race_id
''').fetchall()

# エントリー情報
entry_cache = {}
for race_id, _, _, _ in races:
    entries = db.execute('''
        SELECT e.horse_number, e.horse_id, e.jockey_name
        FROM entries e WHERE e.race_id = ?
    ''', (race_id,)).fetchall()
    if entries:
        entry_cache[race_id] = {e[0]: {'hid': e[1], 'jockey': e[2]} for e in entries}

# 累積騎手成績（レースごとに更新）
jockey_cumulative = defaultdict(lambda: {'rides': 0, 'wins': 0})

# 累積馬成績（直近5走を保持）
horse_recent = defaultdict(list)  # horse_id -> [(race_id, finish_position), ...]

print('=== v3: 未来リーク排除シミュレーション ===')
print('- スマートマネー: 不使用')
print('- 馬成績: レース時点より前の直近5走のみ')
print('- 騎手勝率: レース時点までの累積のみ')
print()

models = [
    ('A: 騎手+馬_alpha0.05', 0.15, 0.05),
    ('B: 騎手+馬_alpha0.10', 0.15, 0.10),
    ('C: 騎手+馬_alpha0.15', 0.15, 0.15),
    ('D: 騎手+馬_alpha0.20', 0.15, 0.20),
    ('E: 騎手+馬_alpha0.30', 0.15, 0.30),
    ('F: 騎手+馬_scale0.10', 0.10, 0.20),
    ('G: 騎手+馬_scale0.20', 0.20, 0.20),
    ('H: 騎手+馬_scale0.25', 0.25, 0.20),
    ('I: 騎手のみ_alpha0.20', 0.15, 0.20),  # special
    ('J: 馬のみ_alpha0.20', 0.15, 0.20),     # special
    ('K: 市場のみ(alpha=0)', 0.15, 0.00),
]

# 時系列順に全レースを処理し、騎手/馬の成績を累積更新
# まず2024-2025のデータで初期化、2026でテスト

print('Phase 1: 2024-2025のデータで騎手/馬の成績を蓄積...')
init_count = 0
for race_id, race_date, _, _ in races:
    if race_date >= '2026-01-01':
        break
    # 成績を累積に追加
    results = db.execute('''
        SELECT horse_number, finish_position, horse_id
        FROM results WHERE race_id = ? AND finish_position IS NOT NULL
    ''', (race_id,)).fetchall()

    for hn, fp, hid in results:
        entry = entry_cache.get(race_id, {}).get(hn, {})
        jname = entry.get('jockey', '')
        if jname:
            jockey_cumulative[jname]['rides'] += 1
            if fp == 1:
                jockey_cumulative[jname]['wins'] += 1
        if hid:
            horse_recent[hid].append(fp)
            if len(horse_recent[hid]) > 5:
                horse_recent[hid] = horse_recent[hid][-5:]
    init_count += 1

print(f'  初期化レース: {init_count}')
print(f'  騎手: {len(jockey_cumulative)}人, 馬: {len(horse_recent)}頭')

# Phase 2: 2026年のシミュレーション
print(f'\nPhase 2: 2026年シミュレーション...\n')

# 各モデルの結果を格納
model_results = {name: {
    'total_bet': 0, 'total_ret': 0, 'total_races': 0, 'total_hits': 0,
    'monthly': defaultdict(lambda: {'bet': 0, 'ret': 0, 'races': 0}),
} for name, _, _ in models}

for race_id, race_date, venue, race_num in races:
    if race_date < '2026-01-01':
        continue

    # 着順取得
    results = db.execute('''
        SELECT horse_number, finish_position, win_odds, horse_id
        FROM results WHERE race_id = ? AND finish_position IS NOT NULL
        ORDER BY finish_position
    ''', (race_id,)).fetchall()
    if len(results) < 5:
        continue

    top3_hn = [r[0] for r in results if r[1] <= 3]
    if len(top3_hn) < 3:
        continue

    # OZ前日オッズ（これはレース前に入手可能）
    oz_win = db.execute(
        "SELECT combination, odds FROM odds WHERE race_id=? AND bet_type='win'",
        (race_id,)
    ).fetchall()
    if not oz_win:
        continue

    oz_map = {int(r[0]): r[1] for r in oz_win}
    hl = sorted(oz_map.keys())
    if len(hl) < 5:
        continue

    early = [oz_map[h] for h in hl]
    month = race_date[:7]

    # 各馬のスコア計算（未来リークなし）
    for mname, scale, alpha in models:
        scores = []
        for h in hl:
            base = 50.0
            entry = entry_cache.get(race_id, {}).get(h, {})

            # 騎手ボーナス（累積、このレースより前のデータのみ）
            jockey_bonus = 0
            if mname != 'J: 馬のみ_alpha0.20':
                jname = entry.get('jockey', '')
                if jname and jname in jockey_cumulative:
                    jc = jockey_cumulative[jname]
                    if jc['rides'] >= 20:
                        jr = jc['wins'] / jc['rides']
                        jockey_bonus = (jr - 0.08) * 50

            # 馬の過去成績ボーナス（このレースより前の直近5走）
            horse_bonus = 0
            if mname != 'I: 騎手のみ_alpha0.20':
                hid = entry.get('hid', '')
                if hid and hid in horse_recent and len(horse_recent[hid]) >= 2:
                    avg = sum(horse_recent[hid]) / len(horse_recent[hid])
                    horse_bonus = (6 - avg) * 2

            scores.append(base + jockey_bonus + horse_bonus)

        mp = softmax(scores, scale)
        mkp = mktp(early)
        bp = blendf(mp, mkp, alpha)

        ranked = sorted(range(len(hl)), key=lambda i: -bp[i])
        top_hn = [hl[r] for r in ranked[:3]]

        # 三連複オッズ取得
        combo = '-'.join(str(h) for h in sorted(top_hn))
        oz_row = db.execute(
            "SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",
            (race_id, combo)
        ).fetchone()
        if not oz_row or oz_row[0] <= 0:
            continue

        odds = oz_row[0] * CORR
        hit = set(top_hn) == set(top3_hn[:3])

        mr = model_results[mname]
        mr['total_bet'] += BUDGET
        mr['total_races'] += 1
        mr['monthly'][month]['bet'] += BUDGET
        mr['monthly'][month]['races'] += 1

        if hit:
            ret = BUDGET * odds
            mr['total_ret'] += ret
            mr['total_hits'] += 1
            mr['monthly'][month]['ret'] += ret

    # レース後に騎手/馬の成績を更新（次のレースから反映）
    for hn, fp, _, hid in results:
        entry = entry_cache.get(race_id, {}).get(hn, {})
        jname = entry.get('jockey', '')
        if jname:
            jockey_cumulative[jname]['rides'] += 1
            if fp == 1:
                jockey_cumulative[jname]['wins'] += 1
        if hid:
            horse_recent[hid].append(fp)
            if len(horse_recent[hid]) > 5:
                horse_recent[hid] = horse_recent[hid][-5:]

# ランキング出力
print(f'{"#":>3} {"モデル":<30} {"レース":>6} {"的中":>5} {"的中率":>7} {"投資":>14} {"払戻":>14} {"収支":>14} {"回収率":>7}')
print('-'*110)

ranked_models = sorted(model_results.items(), key=lambda x: -(x[1]['total_ret']/x[1]['total_bet']*100 if x[1]['total_bet']>0 else 0))

for i, (mname, mr) in enumerate(ranked_models):
    rr = mr['total_ret']/mr['total_bet']*100 if mr['total_bet']>0 else 0
    hr = mr['total_hits']/mr['total_races']*100 if mr['total_races']>0 else 0
    print(f'{i+1:>3} {mname:<30} {mr["total_races"]:>6,} {mr["total_hits"]:>5} {hr:>6.1f}% {mr["total_bet"]:>13,.0f}円 {mr["total_ret"]:>13,.0f}円 {mr["total_ret"]-mr["total_bet"]:>+13,.0f}円 {rr:>6.1f}%')

# 上位3の月別
print('\n=== 上位3モデルの月別推移 ===')
for i, (mname, mr) in enumerate(ranked_models[:3]):
    rr = mr['total_ret']/mr['total_bet']*100 if mr['total_bet']>0 else 0
    print(f'\n--- {i+1}位: {mname} (回収率{rr:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(mr['monthly'].keys()):
        d=mr['monthly'][m]; cb+=d['bet']; cr+=d['ret']
        mr_pct = d['ret']/d['bet']*100 if d['bet']>0 else 0
        print(f'  {m}: {d["races"]:>4}R 月{mr_pct:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

# v2との比較
print('\n=== v2(リークあり) vs v3(リーク排除) 比較 ===')
print(f'v2 1位: SM+騎手+馬_alpha0.30 → 回収率164.8% (リークあり)')
best_v3 = ranked_models[0]
best_rr = best_v3[1]['total_ret']/best_v3[1]['total_bet']*100 if best_v3[1]['total_bet']>0 else 0
print(f'v3 1位: {best_v3[0]} → 回収率{best_rr:.1f}% (リーク排除)')
print(f'差分: {best_rr - 164.8:+.1f}pt')

db.close()
sys.stdout.close()
