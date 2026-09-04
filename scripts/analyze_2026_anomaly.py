"""
2026年だけプラスになった原因分析
"""
import sqlite3, math, sys
from collections import defaultdict

out = open(r'C:\Users\moribro2201\Desktop\analysis_2026.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')
BETA=1.03; SCALE=0.15; ALPHA=0.15; BUDGET=10000

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

races = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races:
    es = db.execute('SELECT horse_number,horse_id,jockey_name FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2]} for e in es}

p('='*80)
p('=== 2026年だけプラスになった原因分析 ===')
p('='*80)

# 1. 基本統計の年別比較
p('\n--- 1. レース数と構成の年別比較 ---')
for year in range(2020, 2027):
    ys = f'{year}-01-01'; ye = f'{year+1}-01-01'
    total = db.execute(f"SELECT COUNT(*) FROM races WHERE race_date>='{ys}' AND race_date<'{ye}'").fetchone()[0]
    turf = db.execute(f"SELECT COUNT(*) FROM races WHERE race_date>='{ys}' AND race_date<'{ye}' AND surface='芝'").fetchone()[0]
    dirt = db.execute(f"SELECT COUNT(*) FROM races WHERE race_date>='{ys}' AND race_date<'{ye}' AND surface='ダート'").fetchone()[0]
    obs = db.execute(f"SELECT COUNT(*) FROM races WHERE race_date>='{ys}' AND race_date<'{ye}' AND surface='障害'").fetchone()[0]
    # 平均頭数
    avg_h = db.execute(f"""
        SELECT AVG(cnt) FROM (
            SELECT COUNT(*) as cnt FROM results r
            JOIN races ra ON r.race_id=ra.race_id
            WHERE ra.race_date>='{ys}' AND ra.race_date<'{ye}'
            GROUP BY r.race_id
        )
    """).fetchone()[0] or 0
    p(f'  {year}: {total}R (芝{turf} ダ{dirt} 障{obs}) 平均頭数{avg_h:.1f}')

# 2. 三連複オッズの分布比較
p('\n--- 2. 三連複オッズの年別分布 ---')
for year in range(2020, 2027):
    rows = db.execute(f"""
        SELECT o.odds FROM odds o
        JOIN races r ON o.race_id = r.race_id
        WHERE o.bet_type='sanrenpuku' AND r.race_date>='{year}-01-01' AND r.race_date<'{year+1}-01-01'
    """).fetchall()
    if not rows: p(f'  {year}: データなし'); continue
    odds_list = [r[0] for r in rows]
    avg = sum(odds_list)/len(odds_list)
    med = sorted(odds_list)[len(odds_list)//2]
    low = sum(1 for o in odds_list if o < 20) / len(odds_list) * 100
    p(f'  {year}: {len(odds_list):,}点 平均{avg:.1f}倍 中央値{med:.1f}倍 20倍以下{low:.1f}%')

# 3. モデルの上位3頭が実際の上位3頭と何頭一致するか（年別）
p('\n--- 3. モデルtop3と実際top3の一致度（年別） ---')
for year in range(2021, 2027):
    train_start = f'{year-2}-01-01'; train_end = f'{year}-01-01'
    jc = defaultdict(lambda:{'r':0,'w':0}); hr = defaultdict(list)
    for rid,rd,vc,sf,dt in races:
        if rd < train_start or rd >= train_end: continue
        res = db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
        for hn,fp,hid in res:
            ent = entry_cache.get(rid,{}).get(hn,{})
            jn = ent.get('jockey','')
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

    match_counts = {0:0, 1:0, 2:0, 3:0}
    mkt_match_counts = {0:0, 1:0, 2:0, 3:0}
    hit_odds = []
    miss_odds = []
    total = 0

    for rid,rd,vc,sf,dt in races:
        if rd < f'{year}-01-01' or rd >= f'{year+1}-01-01': continue
        res = db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
        if len(res)<5: continue
        t3 = [r[0] for r in res if r[1]<=3]
        if len(t3)<3: continue
        oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
        if not oz: continue
        om = {int(r[0]):r[1] for r in oz}; hl = sorted(om.keys())
        if len(hl)<5: continue
        early = [om[h] for h in hl]
        sc = [score(h,rid,vc,sf,dt) for h in hl]
        mp = softmax(sc); mkp = mktp(early); bp = blendf(mp,mkp)
        rk = sorted(range(len(hl)),key=lambda i:-bp[i])
        model_top = set(hl[r] for r in rk[:3])
        mkt_top = set(sorted(hl,key=lambda h:om[h])[:3])
        actual_top = set(t3[:3])

        model_match = len(model_top & actual_top)
        mkt_match = len(mkt_top & actual_top)
        match_counts[model_match] += 1
        mkt_match_counts[mkt_match] += 1

        # 的中時のオッズ
        combo = '-'.join(str(h) for h in sorted(model_top))
        orow = db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if orow and orow[0] > 0:
            if model_match == 3:
                hit_odds.append(orow[0])
            else:
                miss_odds.append(orow[0])

        total += 1

    p(f'\n  {year} ({total}R):')
    p(f'    モデルtop3と実際top3の一致:')
    for m in [3,2,1,0]:
        pct = match_counts[m]/total*100 if total>0 else 0
        p(f'      {m}頭一致: {match_counts[m]:>5} ({pct:.1f}%)')
    p(f'    市場top3と実際top3の一致:')
    for m in [3,2,1,0]:
        pct = mkt_match_counts[m]/total*100 if total>0 else 0
        p(f'      {m}頭一致: {mkt_match_counts[m]:>5} ({pct:.1f}%)')

    avg_hit = sum(hit_odds)/len(hit_odds) if hit_odds else 0
    avg_miss = sum(miss_odds)/len(miss_odds) if miss_odds else 0
    p(f'    的中時の平均オッズ: {avg_hit:.1f}倍 ({len(hit_odds)}件)')
    p(f'    ハズレ時の平均オッズ: {avg_miss:.1f}倍')

# 4. 高額的中の分析
p('\n--- 4. 高額的中（100倍以上）の年別分布 ---')
# 上のループを再利用できないので、簡易版
for year in range(2021, 2027):
    # 的中リストを作り直す必要があるが、ここでは概算
    high_count = db.execute(f"""
        SELECT COUNT(*) FROM odds WHERE bet_type='sanrenpuku' AND odds >= 100
        AND race_id IN (SELECT race_id FROM races WHERE race_date>='{year}-01-01' AND race_date<'{year+1}-01-01')
    """).fetchone()[0]
    total_count = db.execute(f"""
        SELECT COUNT(*) FROM odds WHERE bet_type='sanrenpuku'
        AND race_id IN (SELECT race_id FROM races WHERE race_date>='{year}-01-01' AND race_date<'{year+1}-01-01')
    """).fetchone()[0]
    p(f'  {year}: 100倍以上={high_count:,}/{total_count:,} ({high_count/total_count*100 if total_count>0 else 0:.1f}%)')

# 5. 2026年の的中を1件ずつ確認（大当たりに依存していないか）
p('\n--- 5. 2026年: 大当たり依存度分析 ---')
# 上位の的中を除外した場合の回収率
# (これは別途計算が必要)

# 6. 市場効率性の年別比較（人気別勝率の安定性）
p('\n--- 6. 1番人気の年別勝率 ---')
for year in range(2020, 2027):
    rows = db.execute(f"""
        SELECT r.popularity, r.finish_position FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE ra.race_date>='{year}-01-01' AND ra.race_date<'{year+1}-01-01'
        AND r.popularity = 1 AND r.finish_position IS NOT NULL
    """).fetchall()
    if not rows: continue
    wins = sum(1 for r in rows if r[1]==1)
    places = sum(1 for r in rows if r[1]<=3)
    p(f'  {year}: {len(rows)}R 勝率{wins/len(rows)*100:.1f}% 複勝率{places/len(rows)*100:.1f}%')

# 7. 2026年の月別をより詳細に
p('\n--- 7. 2026年の月別: 大当たり件数 ---')
# 再計算必要なので省略

# 8. データ量の比較
p('\n--- 8. 学習データ量の比較 ---')
for year in range(2021, 2027):
    train_s = f'{year-2}-01-01'; train_e = f'{year}-01-01'
    jc_count = db.execute(f"""
        SELECT COUNT(DISTINCT e.jockey_name) FROM entries e
        JOIN races r ON e.race_id = r.race_id
        WHERE r.race_date>='{train_s}' AND r.race_date<'{train_e}' AND e.jockey_name IS NOT NULL
    """).fetchone()[0]
    horse_count = db.execute(f"""
        SELECT COUNT(DISTINCT e.horse_id) FROM entries e
        JOIN races r ON e.race_id = r.race_id
        WHERE r.race_date>='{train_s}' AND r.race_date<'{train_e}' AND e.horse_id IS NOT NULL
    """).fetchone()[0]
    race_count = db.execute(f"""
        SELECT COUNT(*) FROM races WHERE race_date>='{train_s}' AND race_date<'{train_e}'
    """).fetchone()[0]
    p(f'  {year}用(学習{year-2}-{year-1}): {race_count}R 騎手{jc_count} 馬{horse_count}')

db.close(); out.close()
