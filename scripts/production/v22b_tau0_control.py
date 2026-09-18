# -*- coding: utf-8 -*-
"""v22b: τ=0コントロールテスト（Fable指示）
残差なし（SHのみ）で同じEV≥1.2・確定分母の回収率を出す
→ エッジがモデル残差から来ているか、SH vs プールの価格差から来ているか切り分け

τ=0で110%超 → エッジはSH vs プール価格差（クロスプール検定と矛盾）
τ=0で80%前後 → エッジは残差r（ペア特徴量）から来ている
"""
import sqlite3, math, sys, os, glob, numpy as np
from collections import defaultdict
from itertools import combinations
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
db = sqlite3.connect(DB, timeout=30)
print("Loading...", flush=True)
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'trainer':e[3],'idm':e[4],'total':e[5],'rider':e[6],'run_style':e[7],'weight':e[8]} for e in es}
result_cache = defaultdict(list)
result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3]})
    result_full[row[0]][row[1]] = row[2]
race_horses = {}
for rid,_,_,_,_ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?',(rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)
ts3 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=3 AND odds>0').fetchall():
    ts3[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
db.close()
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978

def sh_umaren_trio(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    umaren=defaultdict(float); trio=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+=pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                trio[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    return umaren, trio

# τ=0: SH確率のみでEV判定（モデル残差なし）
print("Building τ=0 results...", flush=True)
BET = 100

# 券種ごとの結果
results = {'umaren': [], 'sanrenpuku': []}

cdb = sqlite3.connect(DB, timeout=30)
n_proc = 0
for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
    if year < 2024: continue  # テスト年のみ
    hl = race_horses.get(rid, [])
    if len(hl) < 5: continue
    rl = result_cache.get(rid, [])
    if not rl: continue

    o3 = ts3.get(rid, {})
    odds_mkt = o3 if len(o3) >= len(hl)*0.8 else sed.get(rid, {})
    if not odds_mkt: continue

    # 市場確率（3分前オッズ）
    inv_arr = np.array([1/odds_mkt.get(h, 999) for h in hl])
    s = inv_arr.sum()
    if s == 0: continue
    mp = inv_arr/s; mp = mp**1.015; mp /= mp.sum()

    # SH確率（τ=0なのでこれがそのままP_model）
    umaren_p, trio_p = sh_umaren_trio(mp)

    fps = result_full.get(rid, {})
    sorted_h = sorted(odds_mkt.items(), key=lambda x: x[1])
    top8 = [h for h, _ in sorted_h[:8]]

    # confirmed_odds
    co_um = {}; co_tr = {}
    for row in cdb.execute("SELECT bet_type,combination,odds FROM confirmed_odds WHERE race_id=? AND odds>0 AND bet_type IN ('umaren','sanrenpuku')", (rid,)).fetchall():
        if row[0] == 'umaren': co_um[row[1]] = row[2]
        else: co_tr[row[1]] = row[2]

    # 馬連
    top2 = sorted([r for r in rl if r['fp'] in (1, 2)], key=lambda x: x['fp'])
    if len(top2) >= 2 and co_um:
        winner = '-'.join(str(x) for x in sorted([top2[0]['hn'], top2[1]['hn']]))
        for a, b in combinations(top8, 2):
            ai = hl.index(a); bi = hl.index(b)
            key = tuple(sorted([ai, bi]))
            sh_p = umaren_p.get(key, 0)
            if sh_p <= 0: continue
            combo = '-'.join(str(x) for x in sorted([a, b]))
            co = co_um.get(combo, 0)
            if co <= 0: continue
            ev = sh_p * co  # τ=0: P_SH × O_確定
            is_hit = 1 if combo == winner else 0
            payout = co if is_hit else 0
            results['umaren'].append({'year': year, 'ev': ev, 'is_hit': is_hit, 'payout': payout, 'rid': rid})

    # 三連複
    top3 = sorted([r for r in rl if r['fp'] in (1, 2, 3)], key=lambda x: x['fp'])
    if len(top3) >= 3 and co_tr:
        winner = '-'.join(str(x) for x in sorted([top3[0]['hn'], top3[1]['hn'], top3[2]['hn']]))
        for a, b, c in combinations(top8, 3):
            ai = hl.index(a); bi = hl.index(b); ci = hl.index(c)
            key = tuple(sorted([ai, bi, ci]))
            sh_p = trio_p.get(key, 0)
            if sh_p <= 0: continue
            combo = '-'.join(str(x) for x in sorted([a, b, c]))
            co = co_tr.get(combo, 0)
            if co <= 0: continue
            ev = sh_p * co
            is_hit = 1 if combo == winner else 0
            payout = co if is_hit else 0
            results['sanrenpuku'].append({'year': year, 'ev': ev, 'is_hit': is_hit, 'payout': payout, 'rid': rid})

    n_proc += 1
    if n_proc % 2000 == 0: print(f"  {n_proc}R...", flush=True)
cdb.close()

# 結果
print(f"\n{'='*90}")
print("v22b: τ=0 コントロールテスト（SHのみ、モデル残差なし）")
print(f"{'='*90}")

for bt, label in [('umaren', '馬連'), ('sanrenpuku', '三連複')]:
    data = results[bt]
    print(f"\n■ {label} (τ=0)")
    print(f"  {'EV>=':>6} {'n':>7} {'的中':>5} {'的中率':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
    print(f"  {'-'*72}")
    for ev_th in [0.5, 0.8, 1.0, 1.1, 1.2, 1.3, 1.5]:
        sub = [d for d in data if d['ev'] >= ev_th]
        if not sub or len(sub) < 10: continue
        n = len(sub); hits = sum(d['is_hit'] for d in sub); hr = hits/n
        inv = n*BET; pay = sum(d['payout']*BET for d in sub if d['is_hit']); rec = pay/inv*100
        parts = []
        for yr in [2024, 2025, 2026]:
            ys = [d for d in sub if d['year'] == yr]
            if not ys: parts.append(''); continue
            yi = len(ys)*BET; yp = sum(d['payout']*BET for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:.1f}%")
        print(f"  {ev_th:>5.1f} {n:>7} {hits:>5} {hr:>6.2%} {rec:>6.1f}% | {' '.join(parts)}")

    # ブートストラップCI（EV>=1.2）
    sub12 = [d for d in data if d['ev'] >= 1.2]
    if len(sub12) >= 100:
        by_race = defaultdict(list)
        for d in sub12: by_race[d['rid']].append(d)
        rids = list(by_race.keys()); np.random.seed(42); br = []
        for _ in range(5000):
            samp = np.random.choice(rids, size=len(rids), replace=True)
            si = 0; sp = 0
            for r in samp:
                for d in by_race[r]: si += BET; sp += d['payout']*BET if d['is_hit'] else 0
            if si > 0: br.append(sp/si*100)
        br.sort()
        inv = len(sub12)*BET; pay = sum(d['payout']*BET for d in sub12 if d['is_hit'])
        print(f"  CI EV>=1.2: n={len(sub12):,} rec={pay/inv*100:.1f}% 95%CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

# 比較表
print(f"\n{'='*90}")
print("τ=0 vs τ=free 比較（EV>=1.2、確定分母）")
print(f"{'='*90}")
print(f"  {'券種':>8} {'τ=0':>7} {'τ=free(v22)':>12} {'差':>7}")
print(f"  {'-'*40}")
for bt, label, v22_rec in [('umaren', '馬連', 100.8), ('sanrenpuku', '三連複', 118.6)]:
    sub12 = [d for d in results[bt] if d['ev'] >= 1.2]
    if not sub12: continue
    inv = len(sub12)*BET; pay = sum(d['payout']*BET for d in sub12 if d['is_hit'])
    tau0_rec = pay/inv*100
    diff = v22_rec - tau0_rec
    print(f"  {label:>8} {tau0_rec:>6.1f}% {v22_rec:>11.1f}% {diff:>+6.1f}pt")

print("\nDone!")
