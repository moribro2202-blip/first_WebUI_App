# -*- coding: utf-8 -*-
"""全券種モデルの学習・保存（v22g）
単勝: prod_model_v16.txt（既存、変更なし）
馬連: prod_umaren_v22.txt
三連複: prod_trio_v22.txt（既存を上書き）
三連単: prod_trifecta_v22.txt
+ オッズ補正テーブル: prod_odds_calibration.json
"""
import sqlite3, math, sys, os, glob, json, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations, permutations
from scipy.optimize import minimize
from datetime import datetime
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB = os.path.join(BASE, 'data', 'jrdb.db')
JRDB = os.path.join(BASE, 'data', 'jrdb')
MODEL_DIR = os.path.join(BASE, 'data', 'models')
os.makedirs(MODEL_DIR, exist_ok=True)

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
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]:r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_horses = {}
for rid,_,_,_,_ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?',(rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)
ts3 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=3 AND odds>0').fetchall():
    ts3[rid][hn] = odds
ts5 = defaultdict(dict)
for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=5 AND odds>0').fetchall():
    ts5[rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB,'CYB','*.txt'))):
    with open(fpath,'rb') as f:
        for line in f.readlines():
            if len(line)<38: continue
            raw=line.decode('ascii','replace')
            rid2=f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
            try: hn_i=int(raw[8:10]); score=int(raw[33:35].strip())
            except: continue
            cyb_cache[(rid2,hn_i)] = score
db.close()
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
TAKEOUT = {'umaren':0.225,'sanrenpuku':0.25,'sanrentan':0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

# データセット構築 + 補正テーブル用データ
print("Building datasets (2022-2025)...", flush=True)
js={}; hh={}; ts_st={}
ds = {'umaren':{},'trio':{},'trifecta':{}}
FNAMES = {'umaren':None,'trio':None,'trifecta':None}
cal_pairs = {'umaren':[],'sanrenpuku':[],'sanrentan':[]}

cdb = sqlite3.connect(DB, timeout=30)
for rid,rd,vc,sf,dt in races_raw:
    year=int(rd[:4])
    def do_update():
        for res in result_cache.get(rid,[]):
            hn,fp,hid=res['hn'],res['fp'],res['hid']
            ent=entry_cache.get(rid,{}).get(hn,{})
            jn=ent.get('jockey',''); tn=ent.get('trainer','')
            if jn:
                if jn not in js: js[jn]={'r':0,'w':0,'t3':0}
                js[jn]['r']+=1
                if fp==1: js[jn]['w']+=1
                if fp<=3: js[jn]['t3']+=1
            if tn:
                if tn not in ts_st: ts_st[tn]={'r':0,'w':0,'t3':0}
                ts_st[tn]['r']+=1
                if fp==1: ts_st[tn]['w']+=1
                if fp<=3: ts_st[tn]['t3']+=1
            if hid:
                if hid not in hh: hh[hid]=[]
                hh[hid].append({'fp':fp,'dist':dt,'surface':sf})
                if len(hh[hid])>30: hh[hid]=hh[hid][-30:]
    if year<2022 or year>2025: do_update(); continue
    hl=race_horses.get(rid,[])
    if len(hl)<5: do_update(); continue
    rl=result_cache.get(rid,[])
    if not rl: do_update(); continue
    winners=[r['hn'] for r in rl if r['fp']==1]
    if not winners or winners[0] not in hl: do_update(); continue
    o3=ts3.get(rid,{}); o5=ts5.get(rid,{})
    odds_mkt=o3 if len(o3)>=len(hl)*0.8 else sed.get(rid,{})
    has_move=len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
    entries=entry_cache.get(rid,{}); n=len(hl)
    inv_arr=np.array([1/odds_mkt.get(h,999) for h in hl]); s=inv_arr.sum()
    if s==0: do_update(); continue
    mp=inv_arr/s; mp=mp**1.015; mp/=mp.sum()
    idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
    riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
    ozd=oz_cache.get(rid,{}); mkt_d=odds_mkt
    oz_inv={h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
    mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
    oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
    cyb_scores=[cyb_cache.get((rid,h),0) for h in hl]
    avg_cyb=np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0
    fps=result_full.get(rid,{})
    p2=mp**LAM2; p3=mp**LAM3; S1=mp.sum(); S2=p2.sum(); S3=p3.sum()
    umaren_sh=defaultdict(float); trio_sh=defaultdict(float); trifecta_sh={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(mp[i]/S1)*(p2[j]/d2); umaren_sh[tuple(sorted([i,j]))]+=pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                trio_sh[tuple(sorted([i,j,k]))]+=pijk; trifecta_sh[(i,j,k)]=pijk
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    top8=[h for h,_ in sorted_h[:8]]
    top1_idx=np.argmax(mp); top1_hn=hl[top1_idx]; top1_p=mp[top1_idx]
    feats_h={}
    for i,h in enumerate(hl):
        ent=entries.get(h,{}); hid=ent.get('hid',''); f={}
        f['idm_c']=(ent.get('idm') or 50)-avg_idm; f['rider_c']=(ent.get('rider') or 0)-avg_rider
        f['total_index']=ent.get('total') or 0
        oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
        f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
        f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
        jn=ent.get('jockey',''); tn=ent.get('trainer','')
        jst=js.get(jn,{}); f['jockey_t3rate']=jst.get('t3',0)/jst['r'] if jst.get('r',0)>=30 else -1
        tst=ts_st.get(tn,{}); f['trainer_t3rate']=tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
        runs=hh.get(hid,[])
        f['horse_runs']=len(runs)
        if runs:
            rc=runs[-5:]; f['avg_fp_5']=np.mean([r['fp'] for r in rc])
            f['top3_rate']=sum(1 for r in runs if r['fp']<=3)/len(runs)
            f['last_fp']=runs[-1]['fp']
            f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
        else: f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        f['win_odds_3min']=o3.get(h,0); feats_h[h]=f

    top2_fps=sorted([r for r in rl if r['fp'] in (1,2)],key=lambda x:x['fp'])
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    co_um={}; co_tr={}; co_st={}
    for row in cdb.execute("SELECT bet_type,combination,odds FROM confirmed_odds WHERE race_id=? AND odds>0 AND bet_type IN ('umaren','sanrenpuku','sanrentan')",(rid,)).fetchall():
        if row[0]=='umaren': co_um[row[1]]=row[2]
        elif row[0]=='sanrenpuku': co_tr[row[1]]=row[2]
        elif row[0]=='sanrentan': co_st[row[1]]=row[2]

    # 馬連
    if len(top2_fps)>=2:
        winner_um='-'.join(str(x) for x in sorted([top2_fps[0]['hn'],top2_fps[1]['hn']]))
        if year not in ds['umaren']: ds['umaren'][year]={'X':[],'y':[],'init':[],'meta':[]}
        for a,b in combinations(top8,2):
            ai=hl.index(a); bi=hl.index(b); key=tuple(sorted([ai,bi]))
            sh_p=umaren_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b]))
            est_o=(1/sh_p)*(1-TAKEOUT['umaren'])
            conf_o=co_um.get(combo,0)
            if conf_o>0: cal_pairs['umaren'].append((est_o,conf_o))
            pf={}; f1=feats_h[a]; f2=feats_h[b]
            for k in FEAT_KEYS: pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0); pf[f'{k}_diff']=abs(f1.get(k,0)-f2.get(k,0))
            ow1=f1.get('win_odds_3min',0); ow2=f2.get('win_odds_3min',0)
            pf['win_odds_ratio']=min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
            pf['win_odds_sum_inv']=(1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
            if FNAMES['umaren'] is None: FNAMES['umaren']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_um else 0
            ds['umaren'][year]['X'].append([pf.get(k,0) for k in FNAMES['umaren']])
            ds['umaren'][year]['y'].append(is_hit); ds['umaren'][year]['init'].append(init)
            ds['umaren'][year]['meta'].append((rid,combo))
    # 三連複
    if len(top3_fps)>=3:
        winner_tr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in ds['trio']: ds['trio'][year]={'X':[],'y':[],'init':[],'meta':[]}
        for a,b,c in combinations(top8,3):
            ai=hl.index(a); bi=hl.index(b); ci=hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c]))
            est_o=(1/sh_p)*(1-TAKEOUT['sanrenpuku'])
            conf_o=co_tr.get(combo,0)
            if conf_o>0: cal_pairs['sanrenpuku'].append((est_o,conf_o))
            pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
            for k in FEAT_KEYS:
                v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
            odds_list=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
            pf['win_odds_top_ratio']=odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
            pf['win_odds_sum_inv']=sum(1/o for o in odds_list if o>0)
            if FNAMES['trio'] is None: FNAMES['trio']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_tr else 0
            ds['trio'][year]['X'].append([pf.get(k,0) for k in FNAMES['trio']])
            ds['trio'][year]['y'].append(is_hit); ds['trio'][year]['init'].append(init)
            ds['trio'][year]['meta'].append((rid,combo))
        # 三連単
        if top1_p>=0.35:
            winner_st=f"{top3_fps[0]['hn']}-{top3_fps[1]['hn']}-{top3_fps[2]['hn']}"
            if year not in ds['trifecta']: ds['trifecta'][year]={'X':[],'y':[],'init':[],'meta':[]}
            other7=[h for h in top8 if h!=top1_hn][:7]
            for b_h,c_h in permutations(other7,2):
                bi=hl.index(b_h); ci=hl.index(c_h)
                sh_p=trifecta_sh.get((top1_idx,bi,ci),0)
                if sh_p<=0: continue
                combo=f"{top1_hn}-{b_h}-{c_h}"
                est_o=(1/sh_p)*(1-TAKEOUT['sanrentan'])
                conf_o=co_st.get(combo,0)
                if conf_o>0: cal_pairs['sanrentan'].append((est_o,conf_o))
                pf={}; f1=feats_h[top1_hn]; f2=feats_h[b_h]; f3=feats_h[c_h]
                for k in FEAT_KEYS:
                    v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                    pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
                pf['first_odds']=f1.get('win_odds_3min',0)
                pf['second_odds']=f2.get('win_odds_3min',0)
                pf['third_odds']=f3.get('win_odds_3min',0)
                if FNAMES['trifecta'] is None: FNAMES['trifecta']=sorted(pf.keys())
                init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
                is_hit=1 if combo==winner_st else 0
                ds['trifecta'][year]['X'].append([pf.get(k,0) for k in FNAMES['trifecta']])
                ds['trifecta'][year]['y'].append(is_hit); ds['trifecta'][year]['init'].append(init)
                ds['trifecta'][year]['meta'].append((rid,combo))
    do_update()
cdb.close()

for bt in ds:
    for y in sorted(ds[bt].keys()):
        d=ds[bt][y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64)
        n_r=len(set(m[0] for m in d['meta']))
        print(f"  {bt} {y}: {len(d['X']):,} ({n_r}R)")

# === 補正テーブル構築 ===
print("\nBuilding calibration tables...", flush=True)
cal_tables = {}
for bt_cal in ['umaren','sanrenpuku','sanrentan']:
    pairs = cal_pairs[bt_cal]
    bands = defaultdict(list)
    for est_o, conf_o in pairs:
        if est_o<=0 or conf_o<=0: continue
        if est_o<10: band=(0,10)
        elif est_o<30: band=(10,30)
        elif est_o<100: band=(30,100)
        elif est_o<300: band=(100,300)
        elif est_o<1000: band=(300,1000)
        else: band=(1000,99999)
        bands[band].append(conf_o/est_o)
    table = []
    for band in sorted(bands.keys()):
        if len(bands[band])>=20:
            table.append([band[0],band[1],float(np.median(bands[band]))])
    cal_tables[bt_cal] = table
    print(f"  {bt_cal}: {[(f'{lo}-{hi}',f'{r:.3f}') for lo,hi,r in table]}")

# === モデル学習 (2022-2024学習、2025フィット) ===
lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

train_yrs=[2022,2023,2024]; fit_yr=2025
saved = {}
for bt in ds:
    print(f"\nTraining {bt}...", flush=True)
    avail=[y for y in train_yrs if y in ds[bt]]
    if not avail or fit_yr not in ds[bt]: print(f"  skip"); continue
    X_tr=np.vstack([ds[bt][y]['X'] for y in avail])
    y_tr=np.concatenate([ds[bt][y]['y'] for y in avail])
    init_tr=np.concatenate([ds[bt][y]['init'] for y in avail])
    n_train=len(X_tr)
    print(f"  samples: {n_train:,}")
    model=lgb.train(lgb_p,lgb.Dataset(X_tr,y_tr,feature_name=FNAMES[bt],init_score=init_tr),num_boost_round=300)
    X_f=ds[bt][fit_yr]['X']; y_f=ds[bt][fit_yr]['y']; init_f=ds[bt][fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True)
    rd_f=defaultdict(list)
    for i,(rid,combo) in enumerate(ds[bt][fit_yr]['meta']): rd_f[rid].append(i)
    def neg_ll(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f.items():
            ys=y_f[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
            nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
    b_fit,tau_fit=res.x
    print(f"  b={b_fit:.4f} tau={tau_fit:.4f}")
    # Top features
    imp=model.feature_importance(importance_type='gain')
    top5=sorted(zip(FNAMES[bt],imp),key=lambda x:-x[1])[:5]
    print(f"  top5: {[(f,f'{g:.0f}') for f,g in top5]}")

    model_file=f'prod_{bt}_v22g.txt'
    model.save_model(os.path.join(MODEL_DIR, model_file))
    saved[bt]={'model_file':model_file,'b':float(b_fit),'tau':float(tau_fit),
               'feature_names':FNAMES[bt],'n_samples':n_train}

# === 統合設定ファイル保存 ===
config = {
    'version': 'v22g',
    'trained_on': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'train_years': train_yrs,
    'fit_year': fit_yr,
    'beta': 1.015,
    'lam2': LAM2, 'lam3': LAM3,
    'ev_threshold': 1.2,
    'top_n_horses': 8,
    'trifecta_top1_threshold': 0.35,
    'takeout': TAKEOUT,
    'models': saved,
    'odds_calibration': cal_tables,
    'lgb_params': lgb_p,
}

config_path = os.path.join(MODEL_DIR, 'prod_exotic_v22g.json')
with open(config_path, 'w', encoding='utf-8') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"\n{'='*60}")
print("=== Saved ===")
print(f"  Config: {config_path}")
for bt, info in saved.items():
    print(f"  {bt}: {info['model_file']} (b={info['b']:.4f} tau={info['tau']:.4f})")
print(f"  Calibration: {list(cal_tables.keys())}")
print(f"{'='*60}")
print("Done!")
