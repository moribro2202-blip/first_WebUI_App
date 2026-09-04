"""
v4: 包括的シミュレーション
A) 追加特徴量（距離適性・馬場適性・競馬場適性・近走トレンド）
B) 券種組み合わせ最適化
C) 全て未来リーク排除
"""
import sqlite3, math, sys
from collections import defaultdict

sys.stdout = open(r'C:\Users\moribro2201\Desktop\simulation_v4.txt', 'w', encoding='utf-8')

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

def c2(pr,w,c):
    r=sum(p**L2 for i,p in enumerate(pr) if i!=w); return pr[c]**L2/r if r>0 else 0

def check_hit(bt, parts, top3):
    if bt=='sanrenpuku': return set(parts)==set(top3[:3])
    elif bt=='umaren': return set(parts)==set(top3[:2])
    elif bt=='win': return parts[0]==top3[0]
    elif bt=='wide': return parts[0] in top3 and parts[1] in top3
    elif bt=='umatan': return parts[0]==top3[0] and parts[1]==top3[1]
    return False

# 全レース・エントリー・レース情報をロード
print('Loading data...')
races = db.execute('''
    SELECT r.race_id, r.race_date, r.venue_code, r.surface, r.distance
    FROM races r ORDER BY r.race_date, r.race_id
''').fetchall()

entry_cache = {}
for race_id, _, _, _, _ in races:
    entries = db.execute(
        'SELECT horse_number, horse_id, jockey_name FROM entries WHERE race_id=?', (race_id,)
    ).fetchall()
    if entries:
        entry_cache[race_id] = {e[0]: {'hid':e[1], 'jockey':e[2]} for e in entries}

# 累積データ構造
jockey_cum = defaultdict(lambda: {'rides':0,'wins':0})
horse_results = defaultdict(list)  # hid -> [(race_date, finish_pos, distance, surface, venue)]

# Phase 1: 2024-2025で初期化
print('Phase 1: Initializing with 2024-2025 data...')
for race_id, race_date, venue, surface, distance in races:
    if race_date >= '2026-01-01': break
    res = db.execute(
        'SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',
        (race_id,)
    ).fetchall()
    for hn, fp, hid in res:
        entry = entry_cache.get(race_id, {}).get(hn, {})
        jname = entry.get('jockey','')
        if jname:
            jockey_cum[jname]['rides'] += 1
            if fp == 1: jockey_cum[jname]['wins'] += 1
        if hid:
            horse_results[hid].append({
                'date': race_date, 'fp': fp, 'dist': distance,
                'surface': surface, 'venue': venue
            })
            if len(horse_results[hid]) > 20:
                horse_results[hid] = horse_results[hid][-20:]

print(f'  Jockeys: {len(jockey_cum)}, Horses: {len(horse_results)}')

# スコア計算関数
def calc_score(h, race_id, venue, surface, distance, feature_set):
    base = 50.0
    entry = entry_cache.get(race_id, {}).get(h, {})
    hid = entry.get('hid','')
    jname = entry.get('jockey','')

    # 騎手ボーナス
    jbonus = 0
    if 'jockey' in feature_set and jname and jname in jockey_cum:
        jc = jockey_cum[jname]
        if jc['rides'] >= 20:
            jbonus = (jc['wins']/jc['rides'] - 0.08) * 50

    # 馬の直近成績
    hbonus = 0
    if 'horse' in feature_set and hid and hid in horse_results:
        recs = horse_results[hid]
        if len(recs) >= 2:
            avg = sum(r['fp'] for r in recs[-5:]) / len(recs[-5:])
            hbonus = (6 - avg) * 2

    # 距離適性
    dist_bonus = 0
    if 'distance' in feature_set and hid and hid in horse_results:
        recs = horse_results[hid]
        dist_recs = [r for r in recs if r['dist'] and abs(r['dist'] - distance) <= 200]
        if len(dist_recs) >= 2:
            avg = sum(r['fp'] for r in dist_recs[-5:]) / len(dist_recs[-5:])
            dist_bonus = (6 - avg) * 1.5

    # 馬場適性（芝/ダート）
    surf_bonus = 0
    if 'surface' in feature_set and hid and hid in horse_results:
        recs = horse_results[hid]
        surf_recs = [r for r in recs if r['surface'] == surface]
        if len(surf_recs) >= 2:
            avg = sum(r['fp'] for r in surf_recs[-5:]) / len(surf_recs[-5:])
            surf_bonus = (6 - avg) * 1.5

    # 競馬場適性
    venue_bonus = 0
    if 'venue' in feature_set and hid and hid in horse_results:
        recs = horse_results[hid]
        v_recs = [r for r in recs if r['venue'] == venue]
        if len(v_recs) >= 2:
            avg = sum(r['fp'] for r in v_recs[-5:]) / len(v_recs[-5:])
            venue_bonus = (6 - avg) * 1.0

    # 近走トレンド（直近3走が改善傾向なら加点）
    trend_bonus = 0
    if 'trend' in feature_set and hid and hid in horse_results:
        recs = horse_results[hid]
        if len(recs) >= 3:
            last3 = [r['fp'] for r in recs[-3:]]
            # 着順が下がっている（改善）ならプラス
            if last3[-1] < last3[0]:
                trend_bonus = (last3[0] - last3[-1]) * 0.8

    return base + jbonus + hbonus + dist_bonus + surf_bonus + venue_bonus + trend_bonus

# 実験定義
feature_sets = {
    'v3base': {'jockey','horse'},
    'full': {'jockey','horse','distance','surface','venue','trend'},
    'dist_surf': {'jockey','horse','distance','surface'},
    'jockey_only': {'jockey'},
    'all_no_trend': {'jockey','horse','distance','surface','venue'},
}

bet_strategies = {
    '三連複1点': lambda top, od, rid: [('sanrenpuku', sorted(top[:3]), 10000)],
    '三連複1点+単勝◎': lambda top, od, rid: [
        ('sanrenpuku', sorted(top[:3]), 7000),
        ('win', [top[0]], 3000),
    ],
    '三連複1点+馬連◎○': lambda top, od, rid: [
        ('sanrenpuku', sorted(top[:3]), 6000),
        ('umaren', sorted(top[:2]), 4000),
    ],
    '三連複+馬連+単勝': lambda top, od, rid: [
        ('sanrenpuku', sorted(top[:3]), 5000),
        ('umaren', sorted(top[:2]), 3000),
        ('win', [top[0]], 2000),
    ],
    '三連複+ワイド◎○': lambda top, od, rid: [
        ('sanrenpuku', sorted(top[:3]), 6000),
        ('wide', sorted(top[:2]), 4000),
    ],
    '馬連◎○+三連複': lambda top, od, rid: [
        ('umaren', sorted(top[:2]), 5000),
        ('sanrenpuku', sorted(top[:3]), 5000),
    ],
}

# メインループ
experiments = []

for fname, fset in feature_sets.items():
    for sname, sfn in bet_strategies.items():
        # alpha=0.15固定（v3最適値）
        alpha = 0.15; scale = 0.15
        key = f'{fname} | {sname}'

        # 累積データをリセット（毎回同じ初期状態から）
        # → 不要（全実験で同じ時系列を辿るため共有可能）
        # ただし実装の簡略化のため、スコア計算は毎回同じ累積データを参照

        total_bet=0; total_ret=0; total_races=0; total_hits=0
        monthly = defaultdict(lambda:{'bet':0,'ret':0,'races':0})
        bt_stats = defaultdict(lambda:{'bet':0,'ret':0,'hits':0,'count':0})

        for race_id, race_date, venue, surface, distance in races:
            if race_date < '2026-01-01': continue

            res = db.execute(
                'SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',
                (race_id,)
            ).fetchall()
            if len(res)<5: continue
            top3_hn=[r[0] for r in res if r[1]<=3]
            if len(top3_hn)<3: continue

            oz_win = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(race_id,)).fetchall()
            if not oz_win: continue
            oz_map={int(r[0]):r[1] for r in oz_win}
            hl=sorted(oz_map.keys())
            if len(hl)<5: continue

            early=[oz_map[h] for h in hl]
            scores=[calc_score(h, race_id, venue, surface, distance, fset) for h in hl]
            mp=softmax(scores, scale)
            mkp=mktp(early)
            bp=blendf(mp, mkp, alpha)

            ranked=sorted(range(len(hl)), key=lambda i:-bp[i])
            top_hn=[hl[r] for r in ranked[:4]]

            bets = sfn(top_hn, None, race_id)
            if not bets: continue

            month=race_date[:7]
            rb=0; rr_val=0

            for bt, parts, amount in bets:
                combo='-'.join(str(p) for p in parts)
                oz_bt = bt
                oz_row=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type=? AND combination=?",(race_id,oz_bt,combo)).fetchone()
                if not oz_row or oz_row[0]<=0: continue

                odds=oz_row[0]*CORR
                hit=check_hit(bt, parts, top3_hn)
                rb+=amount
                bt_stats[bt]['count']+=1; bt_stats[bt]['bet']+=amount
                if hit:
                    ret=amount*odds; rr_val+=ret
                    bt_stats[bt]['hits']+=1; bt_stats[bt]['ret']+=ret

            if rb==0: continue
            total_bet+=rb; total_ret+=rr_val; total_races+=1
            monthly[month]['bet']+=rb; monthly[month]['ret']+=rr_val; monthly[month]['races']+=1

        rr=total_ret/total_bet*100 if total_bet>0 else 0
        hr=total_hits  # not used directly
        experiments.append({
            'key':key, 'fname':fname, 'sname':sname,
            'races':total_races, 'bet':total_bet, 'ret':total_ret,
            'profit':total_ret-total_bet, 'rr':rr,
            'monthly':dict(monthly), 'bt_stats':dict(bt_stats),
        })

# 結果を累積データ更新後に出力
# (累積更新は全実験で共通だが、実際にはPhase1で既に完了している)

# ランキング
print(f'\n{"="*120}')
print('=== v4 包括シミュレーション結果 ===')
print(f'{"="*120}')
print(f'{"#":>3} {"特徴量":<18} {"戦略":<22} {"レース":>6} {"投資":>14} {"払戻":>14} {"収支":>14} {"回収率":>7}')
print('-'*105)

for i, r in enumerate(sorted(experiments, key=lambda x:-x['rr'])[:30]):
    print(f'{i+1:>3} {r["fname"]:<18} {r["sname"]:<22} {r["races"]:>6,} {r["bet"]:>13,.0f}円 {r["ret"]:>13,.0f}円 {r["profit"]:>+13,.0f}円 {r["rr"]:>6.1f}%')

# 特徴量別ベスト
print(f'\n{"="*80}')
print('=== 特徴量セット別ベスト（三連複1点戦略） ===')
print(f'{"="*80}')
trio_only = [r for r in experiments if r['sname']=='三連複1点']
for r in sorted(trio_only, key=lambda x:-x['rr']):
    print(f'  {r["fname"]:<20} 回収率{r["rr"]:>6.1f}% 収支{r["profit"]:>+12,.0f}円')

# 戦略別ベスト
print(f'\n{"="*80}')
print('=== 戦略別ベスト（full特徴量） ===')
print(f'{"="*80}')
full_feat = [r for r in experiments if r['fname']=='full']
for r in sorted(full_feat, key=lambda x:-x['rr']):
    print(f'  {r["sname"]:<22} 回収率{r["rr"]:>6.1f}% 収支{r["profit"]:>+12,.0f}円')

# 上位3の月別
print(f'\n{"="*80}')
print('=== 上位3の月別推移 ===')
print(f'{"="*80}')
for i, r in enumerate(sorted(experiments, key=lambda x:-x['rr'])[:3]):
    print(f'\n--- {i+1}位: {r["key"]} (回収率{r["rr"]:.1f}%) ---')
    cb=0;cr=0
    for m in sorted(r['monthly'].keys()):
        d=r['monthly'][m]; cb+=d['bet']; cr+=d['ret']
        print(f'  {m}: {d["races"]:>4}R 月{d["ret"]/d["bet"]*100 if d["bet"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

    # 券種別
    if r['bt_stats']:
        print('  券種別:')
        lb={'win':'単勝','umaren':'馬連','wide':'ワイド','umatan':'馬単','sanrenpuku':'三連複'}
        for bt in ['win','umaren','wide','sanrenpuku']:
            bs=r['bt_stats'].get(bt)
            if not bs or bs['count']==0: continue
            print(f'    {lb.get(bt,bt)}: {bs["count"]:,}点 的中{bs["hits"]:,} 回収{bs["ret"]/bs["bet"]*100 if bs["bet"]>0 else 0:.1f}%')

# v3との比較
print(f'\n{"="*80}')
print('=== v3 vs v4 比較 ===')
print(f'{"="*80}')
print('v3 1位: 騎手+馬_alpha0.15 三連複1点 → 回収率104.8%')
best = sorted(experiments, key=lambda x:-x['rr'])[0]
print(f'v4 1位: {best["key"]} → 回収率{best["rr"]:.1f}%')
print(f'差分: {best["rr"]-104.8:+.1f}pt')

db.close()
sys.stdout.close()
