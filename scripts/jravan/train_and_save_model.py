# -*- coding: utf-8 -*-
"""v5モデルを学習して保存（realtime_engine用）
全期間のデータで学習し、data/models/v5_latest.txt に保存
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB = os.path.join(BASE, 'data', 'jrdb.db')
JRDB = os.path.join(BASE, 'data', 'jrdb')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

db = sqlite3.connect(DB)
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

oz_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
sed_cache = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed_cache[row[0]][row[1]] = row[2]
ts_odds = {}
for rid,hn,mb,odds in db.execute('SELECT race_id,horse_number,minutes_before,odds FROM ts_win_odds WHERE odds>0').fetchall():
    ts_odds[(rid,hn,mb)] = odds
ts_races = set(rid for rid,hn,mb in ts_odds if mb==5)

cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB,'CYB','*.txt'))):
    with open(fpath,'rb') as f:
        for line in f.readlines():
            if len(line)<38: continue
            raw=line.decode('ascii','replace')
            v=raw[0:2];y=raw[2:4];k=raw[4:6];rn=raw[6:8];hn=raw[8:10]
            try: hn_i=int(hn)
            except: continue
            rid=f'{y}{v}{k}{rn}'
            try: score=int(raw[33:35].strip())
            except: score=0
            gm={'A':4,'B':3,'C':2,'D':1}
            cyb_cache[(rid,hn_i)]={'score':score,'cyb_grade':gm.get(raw[35:36].strip(),0)}

db.close()
print("Data loaded.", flush=True)

# Feature builder (same as model_v5_combined.py)
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def build_features(rid, rd, vc, sf, dt, js, hh, ht):
    entries=entry_cache.get(rid,{}); hl=race_horses.get(rid,[])
    if not entries or len(hl)<5: return []
    has_ts=rid in ts_races; nhead=len(hl); tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
    ai=[entries.get(h,{}).get('idm') or 0 for h in hl]; avg_i=sum(ai)/len(ai); mx_i=max(ai)
    std_i=(sum((x-avg_i)**2 for x in ai)/len(ai))**0.5 if ai else 0
    ar=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_r=sum(ar)/len(ar)
    oz=oz_cache.get(rid,{}); sed=sed_cache.get(rid,{})
    oz_inv={h:1/oz[h] for h in hl if h in oz and oz.get(h,0)>0}
    sed_inv={h:1/sed[h] for h in hl if h in sed and sed.get(h,0)>0}
    oz_sum=sum(oz_inv.values()) if oz_inv else 1; sed_sum=sum(sed_inv.values()) if sed_inv else 1
    ts5_all={h:ts_odds.get((rid,h,5),0) for h in hl}
    ts5_inv={h:1/ts5_all[h] for h in hl if ts5_all[h]>0}; ts5_sum=sum(ts5_inv.values()) if ts5_inv else 1
    cyb_scores=[cyb_cache.get((rid,h),{}).get('score',0) for h in hl]; avg_cyb=sum(cyb_scores)/len(cyb_scores) if cyb_scores else 50
    feats=[]
    for h in hl:
        ent=entries.get(h,{}); hid=ent.get('hid',''); idm=ent.get('idm') or 0; rider=ent.get('rider') or 0
        f={'idm':idm,'rider_index':rider,'total_index':ent.get('total') or 0,
           'idm_vs_field':idm-avg_i,'idm_vs_max':idm-mx_i,'idm_zscore':(idm-avg_i)/std_i if std_i>0 else 0,
           'rider_vs_field':rider-avg_r,'combined_index':idm+rider,
           'nhead':nhead,'distance':dt,'surface':sf_map.get(sf,0),'grade':grade_map.get(grade,0),
           'track_cond':tc_map.get(tc,0),'is_senkou':1 if ent.get('run_style','') in ('逃げ','先行') else 0}
        oz_p=oz_inv.get(h,0)/oz_sum if oz_sum>0 else 0; sed_p=sed_inv.get(h,0)/sed_sum if sed_sum>0 else 0
        f['oz_expert_p']=oz_p; f['sed_market_p']=sed_p; f['expert_edge']=oz_p/sed_p if sed_p>0 else 0; f['expert_disagree']=abs(oz_p-sed_p)
        cyb=cyb_cache.get((rid,h),{}); f['cyb_score']=cyb.get('score',0); f['cyb_vs_field']=cyb.get('score',0)-avg_cyb; f['cyb_grade']=cyb.get('cyb_grade',0); f['has_cyb']=1 if cyb.get('score',0)>0 else 0
        if has_ts:
            o5=ts_odds.get((rid,h,5),0); o10=ts_odds.get((rid,h,10),0); o15=ts_odds.get((rid,h,15),0); o30=ts_odds.get((rid,h,30),0)
            f['ts5_log']=math.log(max(o5,1)) if o5>0 else 0; f['ts5_market_p']=ts5_inv.get(h,0)/ts5_sum if ts5_sum>0 else 0
            f['odds_move_30to5']=(o30-o5)/o30 if o30>0 and o5>0 else 0; f['odds_move_15to5']=(o15-o5)/o15 if o15>0 and o5>0 else 0
            me=(o30-o15)/o30 if o30>0 and o15>0 else 0; ml=(o15-o5)/o15 if o15>0 and o5>0 else 0; f['odds_accel']=ml-me
            sp=sorted(ts5_inv.items(),key=lambda x:-x[1]); f['ts5_rank']=next((i+1 for i,(hh2,_) in enumerate(sp) if hh2==h),len(hl))
            f['expert_vs_ts5']=oz_p/(ts5_inv.get(h,0)/ts5_sum) if ts5_inv.get(h,0)>0 else 0
        else:
            for k in ['ts5_log','ts5_market_p','odds_move_30to5','odds_move_15to5','odds_accel','ts5_rank','expert_vs_ts5']: f[k]=-1
        jn=ent.get('jockey',''); jst=js.get(jn,{}); jr=jst.get('r',0)
        f['jockey_winrate']=jst.get('w',0)/jr if jr>=30 else -1; f['jockey_top3rate']=jst.get('t3',0)/jr if jr>=30 else -1
        jv=jst.get(f'v_{vc}',{'r':0,'t3':0}); f['jockey_venue_t3rate']=jv['t3']/jv['r'] if jv['r']>=10 else -1
        hist=hh.get(hid,[])
        f['horse_runs']=len(hist)
        if hist:
            rc=hist[-5:]; f['avg_fp_5']=sum(r['fp'] for r in rc)/len(rc); f['best_fp_5']=min(r['fp'] for r in rc)
            f['top3_rate']=sum(1 for r in hist if r['fp']<=3)/len(hist); f['last_fp']=hist[-1]['fp']
            dr=[r for r in hist if r.get('dist') and abs(r['dist']-dt)<=200]; f['dist_top3rate']=sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
            sr=[r for r in hist if r.get('surface')==sf]; f['surf_top3rate']=sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
            f['trend']=hist[-3]['fp']-hist[-1]['fp'] if len(hist)>=3 else 0
            wd=[r.get('wd') for r in hist[-3:] if r.get('wd') is not None]; f['abs_wd']=abs(wd[-1]) if wd else 0
        else:
            f.update({'avg_fp_5':8,'best_fp_5':8,'top3_rate':0,'last_fp':8,'dist_top3rate':-1,'surf_top3rate':-1,'trend':0,'abs_wd':0})
        tch=ht.get(hid,{}).get(tc,[]); f['track_top3rate']=sum(1 for x in tch if x<=3)/len(tch) if tch else -1
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
            js[jn][vk]['r']+=1; fp<=3 and js[jn][vk].__setitem__('t3',js[jn][vk]['t3']+1)
        if hid:
            hh[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc,'wd':res.get('wd')})
            if len(hh[hid])>30: hh[hid]=hh[hid][-30:]
            if tc: ht[hid][tc].append(fp)

# === Train ===
print("Building training data (all years)...", flush=True)
FNAMES = None; X_all = []; y_all = []
js=defaultdict(dict); hh=defaultdict(list); ht=defaultdict(lambda:defaultdict(list))
for rid,rd,vc,sf,dt in races_raw:
    if rd>='2015-01-01': break
    update_stats(rid,rd,vc,sf,dt,js,hh,ht)

for rid,rd,vc,sf,dt in races_raw:
    if rd<'2015-01-01': continue
    rl=result_cache.get(rid,[])
    if len(rl)<5: continue
    t3=set(r['hn'] for r in rl if r['fp']<=3)
    if len(t3)<3: continue
    feats=build_features(rid,rd,vc,sf,dt,js,hh,ht)
    if not feats: continue
    if FNAMES is None: FNAMES=sorted(feats[0][1].keys())
    for hn,f in feats:
        X_all.append([f.get(k,0) for k in FNAMES])
        y_all.append(1 if hn in t3 else 0)
    update_stats(rid,rd,vc,sf,dt,js,hh,ht)

X_all = np.array(X_all); y_all = np.array(y_all)
print(f"Training data: {len(X_all):,} samples, {sum(y_all):,} positive ({sum(y_all)/len(y_all)*100:.1f}%)")

dtrain = lgb.Dataset(X_all, y_all, feature_name=FNAMES)
params = {'objective':'binary','metric':'binary_logloss','learning_rate':0.03,
          'num_leaves':63,'min_child_samples':30,'feature_fraction':0.7,
          'bagging_fraction':0.7,'bagging_freq':3,'lambda_l1':0.1,'lambda_l2':1.0,
          'verbose':-1,'seed':42}
print("Training LightGBM...", flush=True)
model = lgb.train(params, dtrain, num_boost_round=500)

model_path = os.path.join(MODEL_DIR, 'v5_latest.txt')
model.save_model(model_path)
print(f"\nModel saved: {model_path}")
print(f"Features: {len(FNAMES)}")

# Feature importance
imp = model.feature_importance(importance_type='gain')
fi = sorted(zip(FNAMES, imp), key=lambda x: -x[1])
print(f"\nTop 15 features:")
for name, val in fi[:15]:
    print(f"  {name:<22} {val:>10.1f}")

print(f"\nDone! Model ready for realtime_engine.py")
