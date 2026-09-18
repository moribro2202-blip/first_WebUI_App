# -*- coding: utf-8 -*-
"""発走5分前オッズでのバックテスト
- モデル: LightGBM (NO ODDS特徴量)
- 市場: ts_win_odds テーブルの5分前単勝オッズ
- 戦略: モデルP > 市場P の時だけ賭ける（EV>1）
- 払戻: HJC確定オッズ（実データ）

使い方: python scripts/jravan/backtest_5min.py
"""
import sqlite3, math, sys, numpy as np, lightgbm as lgb
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

import os
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')

db = sqlite3.connect(DB_PATH)
print("Loading...", flush=True)

races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,idm,total_index,rider_index,run_style FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'idm':e[3],'total':e[4],'rider':e[5],'run_style':e[6]} for e in es}
result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id,horse_weight_diff FROM results WHERE finish_position IS NOT NULL ORDER BY race_id,finish_position').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3],'wd':row[4]})
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]:r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_horses = {}
for rid,_,_,_,_ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?',(rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)

# 5分前オッズ (from JRA-VAN time-series)
ts5_cache = defaultdict(dict)  # {race_id: {horse_number: odds}}
ts_count = 0
for rid, hn, odds in db.execute('SELECT race_id, horse_number, odds FROM ts_win_odds WHERE minutes_before=5 AND odds>0').fetchall():
    ts5_cache[rid][hn] = odds
    ts_count += 1
print(f"5分前オッズ: {ts_count:,} records, {len(ts5_cache)} races")

# 確定オッズ (ts minutes_before=0)
ts0_cache = defaultdict(dict)
for rid, hn, odds in db.execute('SELECT race_id, horse_number, odds FROM ts_win_odds WHERE minutes_before=0 AND odds>0').fetchall():
    ts0_cache[rid][hn] = odds
print(f"確定オッズ(JRA-VAN): {len(ts0_cache)} races")

# SED confirmed odds (backup)
sed_cache = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed_cache[row[0]][row[1]] = row[2]

# HJC payout
hjc_win = defaultdict(dict)
for rid,combo,odds in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    hjc_win[rid][combo] = odds

db.close()
print("Data loaded.", flush=True)

# === Features (NO ODDS) ===
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def build_features(rid, rd, vc, sf, dt, js, hh, ht):
    entries=entry_cache.get(rid,{}); hl=race_horses.get(rid,[])
    if not entries or len(hl)<5: return []
    nhead=len(hl); tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
    ai=[entries.get(h,{}).get('idm') or 0 for h in hl]; avg_i=sum(ai)/len(ai); mx_i=max(ai)
    std_i=(sum((x-avg_i)**2 for x in ai)/len(ai))**0.5 if ai else 0
    ar=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_r=sum(ar)/len(ar)
    feats=[]
    for h in hl:
        ent=entries.get(h,{}); hid=ent.get('hid','')
        idm=ent.get('idm') or 0; rider=ent.get('rider') or 0
        f={'idm':idm,'rider_index':rider,'total_index':ent.get('total') or 0,
           'idm_vs_field':idm-avg_i,'idm_vs_max':idm-mx_i,
           'idm_zscore':(idm-avg_i)/std_i if std_i>0 else 0,
           'rider_vs_field':rider-avg_r,'combined_index':idm+rider,
           'nhead':nhead,'distance':dt,'surface':sf_map.get(sf,0),
           'grade':grade_map.get(grade,0),'track_cond':tc_map.get(tc,0),
           'is_senkou':1 if ent.get('run_style','') in ('逃げ','先行') else 0}
        jn=ent.get('jockey',''); jst=js.get(jn,{}); jr=jst.get('r',0)
        f['jockey_winrate']=jst.get('w',0)/jr if jr>=30 else -1
        f['jockey_top3rate']=jst.get('t3',0)/jr if jr>=30 else -1
        jv=jst.get(f'v_{vc}',{'r':0,'t3':0})
        f['jockey_venue_t3rate']=jv['t3']/jv['r'] if jv['r']>=10 else -1
        hist=hh.get(hid,[])
        f['horse_runs']=len(hist)
        if hist:
            rc=hist[-5:]
            f['avg_fp_5']=sum(r['fp'] for r in rc)/len(rc)
            f['best_fp_5']=min(r['fp'] for r in rc)
            f['top3_rate']=sum(1 for r in hist if r['fp']<=3)/len(hist)
            f['last_fp']=hist[-1]['fp']
            dr=[r for r in hist if r.get('dist') and abs(r['dist']-dt)<=200]
            f['dist_top3rate']=sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
            sr=[r for r in hist if r.get('surface')==sf]
            f['surf_top3rate']=sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
            f['trend']=hist[-3]['fp']-hist[-1]['fp'] if len(hist)>=3 else 0
            wd=[r.get('wd') for r in hist[-3:] if r.get('wd') is not None]
            f['abs_wd']=abs(wd[-1]) if wd else 0
        else:
            f.update({'avg_fp_5':8,'best_fp_5':8,'top3_rate':0,'last_fp':8,
                      'dist_top3rate':-1,'surf_top3rate':-1,'trend':0,'abs_wd':0})
        tch=ht.get(hid,{}).get(tc,[])
        f['track_top3rate']=sum(1 for x in tch if x<=3)/len(tch) if tch else -1
        feats.append((h,f))
    return feats

def update_stats(rid, rd, vc, sf, dt, js, hh, ht):
    tc=race_cond.get(rid,'良')
    for res in result_cache.get(rid,[]):
        hn,fp,hid=res['hn'],res['fp'],res['hid']
        ent=entry_cache.get(rid,{}).get(hn,{})
        jn=ent.get('jockey','')
        if jn:
            js[jn]['r']=js[jn].get('r',0)+1
            if fp==1: js[jn]['w']=js[jn].get('w',0)+1
            if fp<=3: js[jn]['t3']=js[jn].get('t3',0)+1
            vk=f'v_{vc}'
            if vk not in js[jn]: js[jn][vk]={'r':0,'t3':0}
            js[jn][vk]['r']+=1
            if fp<=3: js[jn][vk]['t3']+=1
        if hid:
            hh[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'wd':res.get('wd')})
            if len(hh[hid])>30: hh[hid]=hh[hid][-30:]
            if tc: ht[hid][tc].append(fp)

# === Build datasets ===
print("Building features...", flush=True)
FNAMES=None; datasets={}
js=defaultdict(dict); hh=defaultdict(list); ht=defaultdict(lambda:defaultdict(list))
for rid,rd,vc,sf,dt in races_raw:
    if rd>='2016-01-01': break
    update_stats(rid,rd,vc,sf,dt,js,hh,ht)
TY=list(range(2016,2027)); B=10000
for ty in TY:
    X=[]; y=[]; meta=[]
    for rid,rd,vc,sf,dt in races_raw:
        if rd<f'{ty}-01-01': continue
        if rd>=f'{ty+1}-01-01': break
        rl=result_cache.get(rid,[])
        if len(rl)<5: continue
        t3=set(r['hn'] for r in rl if r['fp']<=3)
        if len(t3)<3: continue
        feats=build_features(rid,rd,vc,sf,dt,js,hh,ht)
        if not feats: continue
        if FNAMES is None: FNAMES=sorted(feats[0][1].keys())
        for hn,f in feats:
            X.append([f.get(k,0) for k in FNAMES])
            y.append(1 if hn in t3 else 0)
            meta.append((rid,hn))
        update_stats(rid,rd,vc,sf,dt,js,hh,ht)
    if X: datasets[ty]=(np.array(X),np.array(y),meta); print(f"  {ty}: {len(X)}", flush=True)

# === Walk-forward with 5-min odds ===
print(f"\n{'='*100}")
print("=== バックテスト: モデルP vs 5分前オッズ → HJC払戻 ===")
print(f"{'='*100}")

EDGE_TH = [0.0, 1.0, 1.2, 1.5, 2.0]
res = {th: {y:{'b':0,'r':0,'h':0,'n':0} for y in TY} for th in EDGE_TH}

# Also compare: SED(確定) vs 5分前 vs JRA-VAN確定
compare = {src: {y:{'b':0,'r':0,'h':0} for y in TY} for src in ['SED確定','5分前','JRAVAN確定']}

for test_year in TY:
    if test_year not in datasets: continue
    train_years=[y for y in TY if y<test_year and y in datasets]
    if not train_years: continue
    X_tr=np.vstack([datasets[y][0] for y in train_years])
    y_tr=np.concatenate([datasets[y][1] for y in train_years])
    X_te,y_te,meta_te=datasets[test_year]
    dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES)
    params={'objective':'binary','metric':'binary_logloss','learning_rate':0.05,
            'num_leaves':31,'min_child_samples':50,'feature_fraction':0.8,
            'bagging_fraction':0.8,'bagging_freq':5,'verbose':-1,'seed':42}
    mdl=lgb.train(params,dtrain,num_boost_round=300)
    probs=mdl.predict(X_te)

    race_data=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te):
        race_data[rid].append((hn,probs[i]))

    has_ts5 = 0; no_ts5 = 0
    for rid,preds in race_data.items():
        rl=result_cache.get(rid,[])
        if not rl: continue
        winner=[r['hn'] for r in rl if r['fp']==1]
        if not winner: continue
        winner=winner[0]

        model_p={hn:p for hn,p in preds}
        ranked=sorted(preds,key=lambda x:-x[1])
        pick=ranked[0][0]

        # 5分前オッズ
        ts5=ts5_cache.get(rid,{})
        if not ts5:
            no_ts5 += 1
            continue
        has_ts5 += 1

        # 5分前の市場確率
        ts5_inv={h:1/ts5[h] for h in ts5 if ts5[h]>0}
        ts5_sum=sum(ts5_inv.values()) if ts5_inv else 1
        ts5_p={h:ts5_inv[h]/ts5_sum for h in ts5_inv}

        pick_model_p = model_p.get(pick, 0)
        pick_ts5_p = ts5_p.get(pick, 0)

        # Edge = model P / market 5min P
        edge = pick_model_p / pick_ts5_p if pick_ts5_p > 0 else 0

        for th in EDGE_TH:
            if th == 0.0 or edge >= th:
                res[th][test_year]['b'] += B
                res[th][test_year]['n'] += 1
                if pick == winner:
                    res[th][test_year]['h'] += 1
                    hv = hjc_win.get(rid, {}).get(str(pick), 0)
                    if hv > 0:
                        res[th][test_year]['r'] += int(B * hv)

        # Compare: different odds sources for payout (always bet on model #1)
        for src, cache in [('SED確定', sed_cache), ('5分前', ts5_cache), ('JRAVAN確定', ts0_cache)]:
            compare[src][test_year]['b'] += B
            if pick == winner:
                compare[src][test_year]['h'] += 1
                odds_val = cache.get(rid, {}).get(pick if src != 'SED確定' else pick, 0)
                if src == 'SED確定':
                    odds_val = sed_cache.get(rid, {}).get(pick, 0)
                if odds_val > 0:
                    compare[src][test_year]['r'] += int(B * odds_val)

    print(f"  {test_year}: ts5={has_ts5}R, no_ts5={no_ts5}R", flush=True)

# === Output ===
print(f"\n{'='*100}")
print("=== 結果1: Edge閾値別（モデルP / 5分前市場P ≥ 閾値）===")
print(f"{'='*100}")
print(f"  {'Edge≥':>6} {'R数':>7} {'的中':>5} {'率':>5} {'HJC%':>6} {'収支':>12} {'+年':>5}")
print(f"  {'-'*55}")
for th in EDGE_TH:
    tb=sum(v['b'] for v in res[th].values())
    tr=sum(v['r'] for v in res[th].values())
    total_h=sum(v['h'] for v in res[th].values())
    tn=sum(v['n'] for v in res[th].values())
    if tn<10: continue
    rr=tr/tb*100; hr_=total_h/tn*100
    plus=sum(1 for y in TY if res[th][y]['b']>0 and res[th][y]['r']/res[th][y]['b']>=1.0)
    ny=sum(1 for y in TY if res[th][y]['b']>0)
    mk=' <<<' if rr>=100 else '  <<' if rr>=90 else '   <' if rr>=80 else ''
    print(f"  {th:>5.1f}x {tn:>7,} {total_h:>5,} {hr_:>4.1f}% {rr:>5.1f}% {tr-tb:>+11,}円 {plus:>3}/{ny}{mk}")

# Yearly for best edge
print(f"\n{'='*100}")
print("=== 年別: Edge≥1.0（モデルP > 5分前市場P）===")
print(f"{'='*100}")
th = 1.0
for y in TY:
    s=res[th][y]
    if s['b']==0: continue
    rr=s['r']/s['b']*100
    mk='<<<' if rr>=110 else ' <<' if rr>=100 else '  <' if rr>=90 else ''
    print(f"  {y}: {s['n']:>5}R 的中{s['h']:>4} ({s['h']/s['n']*100 if s['n']>0 else 0:.1f}%) HJC={rr:.1f}% {mk}")

# === Compare odds sources ===
print(f"\n{'='*100}")
print("=== 結果2: オッズ源泉比較（モデル#1に全賭け、払戻を各オッズで計算）===")
print(f"{'='*100}")
print(f"  {'源泉':<15} {'R数':>6} {'的中':>5} {'回収率':>6}")
print(f"  {'-'*40}")
for src in ['5分前','JRAVAN確定','SED確定']:
    tb=sum(v['b'] for v in compare[src].values())
    tr=sum(v['r'] for v in compare[src].values())
    th_=sum(v['h'] for v in compare[src].values())
    if tb>0:
        print(f"  {src:<15} {tb//B:>6} {th_:>5} {tr/tb*100:>5.1f}%")

print(f"\nDone!")
