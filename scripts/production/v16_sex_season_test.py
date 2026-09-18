# -*- coding: utf-8 -*-
"""性別×季節の特徴量テスト（moveなし、全馬、EVフィルタなし）"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
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
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3]})
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]:r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
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
oz_cache = {}
for rid,_,_,_,_ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if oz: oz_cache[rid] = {int(r[0]):r[1] for r in oz}
hjc_cache = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try: hjc_cache[row[0]][int(row[1])] = row[2]
    except: pass
cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB,'CYB','*.txt'))):
    with open(fpath,'rb') as f:
        for line in f.readlines():
            if len(line)<38: continue
            raw=line.decode('ascii','replace')
            rid2=raw[2:4]+raw[0:2]+raw[4:6]+raw[6:8]
            try: hn_i=int(raw[8:10]); score=int(raw[33:35].strip())
            except: continue
            cyb_cache[(rid2,hn_i)] = score

# 性別
sex_cache = {}
for row in db.execute('SELECT horse_id, sex FROM horses WHERE sex IS NOT NULL').fetchall():
    sex_cache[row[0]] = row[1]  # '牡','牝','セ'
db.close()
print(f"Loaded. sex_cache: {len(sex_cache):,}", flush=True)

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}
SEX_MAP = {'牡':0, '牝':1, 'セ':2}

def run(extra_features, label):
    js={}; hh={}; ts_st={}; datasets={}; FNAMES=None
    for rid,rd,vc,sf,dt in races_raw:
        year=int(rd[:4]); month=int(rd[5:7])
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
        if year<2022: do_update(); continue
        if year not in datasets:
            datasets[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
        hl=race_horses.get(rid,[])
        if len(hl)>=5:
            rl=result_cache.get(rid,[])
            if rl:
                winners=[r['hn'] for r in rl if r['fp']==1]
                if winners and winners[0] in hl:
                    odds_mkt=ts3.get(rid,{})
                    if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
                    inv=np.array([1/odds_mkt.get(h,999) for h in hl])
                    s=inv.sum()
                    if s==0: do_update(); continue
                    mp=inv/s; mp=mp**1.015; mp/=mp.sum()
                    entries=entry_cache.get(rid,{}); n=len(hl)
                    tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
                    idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
                    riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
                    ozd=oz_cache.get(rid,{}); mkt_d=odds_mkt
                    oz_inv={h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
                    mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
                    oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
                    cyb_scores=[cyb_cache.get((rid,h),0) for h in hl]
                    avg_cyb=np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0
                    for i,h in enumerate(hl):
                        ent=entries.get(h,{}); hid=ent.get('hid','')
                        f={}
                        f['idm_c']=(ent.get('idm') or 50)-avg_idm
                        f['rider_c']=(ent.get('rider') or 0)-np.mean(riders)
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
                            dr=[r for r in runs if abs(r.get('dist',0)-dt)<=200]
                            f['dist_t3rate']=sum(1 for r in dr if r['fp']<=3)/len(dr) if dr else -1
                            sr=[r for r in runs if r.get('surface')==sf]
                            f['surf_t3rate']=sum(1 for r in sr if r['fp']<=3)/len(sr) if sr else -1
                            f['trend']=runs[-3]['fp']-runs[-1]['fp'] if len(runs)>=3 else 0
                            f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
                        else:
                            f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'dist_t3rate':-1,'surf_t3rate':-1,'trend':0,'win_rate':-1})
                        f['nhead']=n; f['distance']=dt; f['surface']=sf_map.get(sf,0)
                        f['track_cond']=tc_map.get(tc,0); f['grade']=grade_map.get(grade,0)
                        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
                        f['gate_ratio']=h/n
                        cw=ent.get('weight') or 0
                        avg_cw=np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in hl])
                        f['weight_c']=(cw-avg_cw) if cw>0 else 0

                        # 追加特徴量
                        if 'sex' in extra_features:
                            sex_str = sex_cache.get(hid, '牡')
                            f['sex'] = SEX_MAP.get(sex_str, 0)
                        if 'month' in extra_features:
                            f['month'] = month
                        if 'is_summer' in extra_features:
                            f['is_summer'] = 1 if month in (6,7,8,9) else 0
                        if 'is_female_summer' in extra_features:
                            sex_str = sex_cache.get(hid, '牡')
                            is_female = 1 if sex_str == '牝' else 0
                            is_summer = 1 if month in (6,7,8,9) else 0
                            f['is_female_summer'] = is_female * is_summer

                        if FNAMES is None: FNAMES=sorted(f.keys())
                        datasets[year]['X'].append([f.get(k,0) for k in FNAMES])
                        datasets[year]['y'].append(1 if h==winners[0] else 0)
                        datasets[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
                        datasets[year]['meta'].append((rid,h))
                        datasets[year]['odds'].append(ts3.get(rid,{}).get(h,0))
        do_update()
    for y in sorted(datasets.keys()):
        d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])

    params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
    all_data=[]
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in datasets]
        fit_yr=test_yr-1
        if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
        X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
        y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
        dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr)
        model=lgb.train(params,dtrain,num_boost_round=300)
        X_f=datasets[fit_yr]['X']; y_f=datasets[fit_yr]['y']; init_f=datasets[fit_yr]['init']
        meta_f=datasets[fit_yr]['meta']; raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_f): rd_f[rid].append(i)
        def neg_ll(p):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        b_use,tau_use=res.x
        X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']; init_te=datasets[test_yr]['init']
        meta_te=datasets[test_yr]['meta']; odds_te=datasets[test_yr]['odds']
        raw_te=model.predict(X_te,raw_score=True)
        race_data=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_te): race_data[rid].append(i)
        mkt_nll=0; model_nll=0; n_races=0
        for rid2,idxs in race_data.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            mp_te=1/(1+np.exp(-init_te[idxs])); mp_norm=mp_te/mp_te.sum()
            mkt_nll-=math.log(max(mp_norm[wi[0]],1e-15))
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            p_raw=np.exp(s)/np.exp(s).sum()
            model_nll-=math.log(max(p_raw[wi[0]],1e-15))
            n_races+=1
            hns=[meta_te[i][1] for i in idxs]; winner=hns[wi[0]]
            hjc=hjc_cache.get(rid2,{})
            for j,idx in enumerate(idxs):
                o=odds_te[idx]
                if o<=0: continue
                all_data.append({'year':test_yr,'ev':float(p_raw[j]*o),'is_hit':int(hns[j]==winner),
                                 'payout':hjc.get(hns[j],0) if hns[j]==winner else 0,'odds':o,'p':float(p_raw[j])})
        delta=(mkt_nll-model_nll)/n_races if n_races>0 else 0
        print(f"    {test_yr}: Δ_τ={delta:+.5f}")

    n=len(all_data); inv=n*100; pay=sum(d['payout']*100 for d in all_data if d['is_hit'])
    rec=pay/inv*100 if inv>0 else 0
    avg_p=np.mean([d['p'] for d in all_data]); avg_hit=np.mean([d['is_hit'] for d in all_data])
    ratio=avg_hit/avg_p if avg_p>0 else 0
    # 新特徴量のgain
    imp=dict(zip(FNAMES, model.feature_importance(importance_type='gain')))
    new_feats={k:v for k,v in imp.items() if k in ('sex','month','is_summer','is_female_summer')}
    print(f"\n  {label} ({len(FNAMES)}特徴量)")
    print(f"  全馬: n={n:,} 回収率={rec:.1f}% 比={ratio:.2f}")
    if new_feats:
        print(f"  新特徴量gain: {new_feats}")

print("="*80)
print("性別×季節テスト（moveなし、全馬、EVフィルタなし）")
print("="*80)
run([], "BASE（現行23特徴量）")
run(['sex'], "+sex（性別3値）")
run(['month'], "+month（月1-12）")
run(['sex','month'], "+sex+month")
run(['is_summer'], "+is_summer（6-9月=1）")
run(['is_female_summer'], "+is_female_summer（牝馬×夏=1）")
run(['sex','month','is_female_summer'], "+sex+month+female_summer")
print("\nDone!")
