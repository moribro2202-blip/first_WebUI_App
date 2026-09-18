# -*- coding: utf-8 -*-
"""2022年以降のみウォークフォワード
2015-2021のスナップショットは偽（締切後の値）なので除外
"""
import sqlite3, math, sys, os, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB)
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
ts_odds = {}
for mb in [0,1,2,3,5]:
    ts_odds[mb] = defaultdict(dict)
    for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=? AND odds>0',(mb,)).fetchall():
        ts_odds[mb][rid][hn] = odds
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
db.close()
print("Loaded.", flush=True)

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

def run_wf(mf, mt, mkt, label):
    js={}; hh={}; ts_st={}
    datasets = {}; FNAMES = None
    for rid,rd,vc,sf,dt in races_raw:
        year = int(rd[:4])
        def do_update():
            for res in result_cache.get(rid,[]):
                hn,fp,hid = res['hn'],res['fp'],res['hid']
                ent = entry_cache.get(rid,{}).get(hn,{})
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
        if year < 2022:
            do_update(); continue
        if year not in datasets:
            datasets[year] = {'X':[],'y':[],'init':[],'meta':[],'odds_judge':[]}
        hl = race_horses.get(rid,[])
        if len(hl)>=5:
            rl = result_cache.get(rid,[])
            if rl:
                winners = [r['hn'] for r in rl if r['fp']==1]
                if winners and winners[0] in hl:
                    odds_mkt = ts_odds[mkt].get(rid,{})
                    if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
                    inv=np.array([1/odds_mkt.get(h,999) for h in hl])
                    s=inv.sum()
                    if s==0: do_update(); continue
                    mp=inv/s; mp=mp**1.015; mp/=mp.sum()
                    o_from=ts_odds[mf].get(rid,{}); o_to=ts_odds[mt].get(rid,{})
                    has_move=len(o_from)>=len(hl)*0.8 and len(o_to)>=len(hl)*0.8
                    entries=entry_cache.get(rid,{}); n=len(hl)
                    tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
                    idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
                    riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
                    oz=oz_cache.get(rid,{}); mkt_d=odds_mkt
                    oz_inv={h:1/oz[h] if h in oz and oz[h]>0 else 0 for h in hl}
                    mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
                    oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
                    for i,h in enumerate(hl):
                        ent=entries.get(h,{}); hid=ent.get('hid','')
                        idm=ent.get('idm') or 50; rider=ent.get('rider') or 0
                        jn=ent.get('jockey',''); tn=ent.get('trainer','')
                        runs=hh.get(hid,[])
                        f={}
                        f['idm_c']=idm-avg_idm; f['rider_c']=rider-avg_rider
                        f['total_index']=ent.get('total') or 0
                        oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
                        f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
                        jst=js.get(jn,{}); jr=jst.get('r',0)
                        f['jockey_t3rate']=jst.get('t3',0)/jr if jr>=30 else -1
                        tst=ts_st.get(tn,{}); tr_r=tst.get('r',0)
                        f['trainer_t3rate']=tst.get('t3',0)/tr_r if tr_r>=30 else -1
                        f['horse_runs']=len(runs)
                        if runs:
                            rc=runs[-5:]
                            f['avg_fp_5']=np.mean([r['fp'] for r in rc])
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
                        if has_move:
                            of=o_from.get(h,0); ot=o_to.get(h,0)
                            f['move']=(of-ot)/of if of>0 and ot>0 else 0
                        else: f['move']=0
                        if FNAMES is None: FNAMES=sorted(f.keys())
                        datasets[year]['X'].append([f.get(k,0) for k in FNAMES])
                        datasets[year]['y'].append(1 if h==winners[0] else 0)
                        p=mp[i]
                        datasets[year]['init'].append(math.log(max(p,1e-15))-math.log(max(1-p,1e-15)))
                        datasets[year]['meta'].append((rid,h))
                        datasets[year]['odds_judge'].append(ts_odds[mkt].get(rid,{}).get(h,0))
        do_update()

    for y in sorted(datasets.keys()):
        d=datasets[y]
        d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds_judge']=np.array(d['odds_judge'])
        print(f"    {y}: {len(d['X']):,}")

    params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

    print(f"\n  {label}")
    print(f"  {'test':>4} {'train_yrs':>12} {'b':>5} {'tau':>5} {'delta':>8} {'nR':>5} | {'n':>5} {'hit':>4} {'rec%':>6} | {'n15':>4} {'h15':>3} {'r15%':>5}")

    all_bets=[]
    for test_yr in [2024, 2025, 2026]:
        train_yrs = [y for y in range(2022, test_yr) if y in datasets]
        fit_yr = test_yr - 1
        if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue

        X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
        y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
        dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr)
        model=lgb.train(params,dtrain,num_boost_round=300)

        # fit b,tau on fit_yr
        X_f=datasets[fit_yr]['X']; y_f=datasets[fit_yr]['y']
        init_f=datasets[fit_yr]['init']; meta_f=datasets[fit_yr]['meta']
        raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_f): rd_f[rid].append(i)
        def neg_ll(p):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]
                s-=s.max(); nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        b_use,tau_use=res.x

        # test
        X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']
        init_te=datasets[test_yr]['init']; meta_te=datasets[test_yr]['meta']
        odds_te=datasets[test_yr]['odds_judge']
        raw_te=model.predict(X_te,raw_score=True)
        race_data=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_te): race_data[rid].append(i)
        mp_te=1/(1+np.exp(-init_te))
        mkt_nll=0; tau_nll=0; n_races=0
        for rid2,idxs in race_data.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            mp_race=mp_te[idxs]; mp_norm=mp_race/mp_race.sum()
            mkt_nll-=math.log(max(mp_norm[wi[0]],1e-15))
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]
            s-=s.max(); tau_p=np.exp(s)/np.exp(s).sum()
            tau_nll-=math.log(max(tau_p[wi[0]],1e-15))
            n_races+=1
            hns=[meta_te[i][1] for i in idxs]; winner=hns[wi[0]]
            hjc=hjc_cache.get(rid2,{})
            for j,idx in enumerate(idxs):
                o=odds_te[idx]
                if o<=0: continue
                ev=tau_p[j]*o; is_hit=(hns[j]==winner)
                payout=hjc.get(hns[j],0) if is_hit else 0
                all_bets.append({'year':test_yr,'ev':ev,'odds':o,'is_hit':is_hit,'payout':payout,'model_p':float(tau_p[j])})

        delta=(mkt_nll-tau_nll)/n_races if n_races>0 else 0
        yb=[b for b in all_bets if b['year']==test_yr and b['ev']>=1.1 and 2<=b['odds']<=30]
        yb15=[b for b in all_bets if b['year']==test_yr and b['ev']>=1.15 and 2<=b['odds']<=30]
        nb=len(yb); hits=sum(1 for b in yb if b['is_hit'])
        inv_t=nb*100; pay_t=sum(b['payout']*100 for b in yb if b['is_hit'])
        rec=pay_t/inv_t*100 if inv_t>0 else 0
        n15=len(yb15); h15=sum(1 for b in yb15 if b['is_hit'])
        inv15=n15*100; pay15=sum(b['payout']*100 for b in yb15 if b['is_hit'])
        rec15=pay15/inv15*100 if inv15>0 else 0
        sign='+' if delta>0 else ''
        print(f"  {test_yr:>4} {str(train_yrs):>12} {b_use:>5.2f} {tau_use:>5.2f} {sign}{delta:.5f} {n_races:>5} | {nb:>5} {hits:>4} {rec:>5.1f}% | {n15:>4} {h15:>3} {rec15:>4.1f}%")

    # totals
    for th, lbl in [(1.1, "EV>=1.10"), (1.15, "EV>=1.15"), (1.05, "EV>=1.05")]:
        fb=[b for b in all_bets if b['ev']>=th and 2<=b['odds']<=30]
        if not fb: continue
        n=len(fb); h=sum(1 for b in fb if b['is_hit'])
        inv_t=n*100; pay_t=sum(b['payout']*100 for b in fb if b['is_hit'])
        rec=pay_t/inv_t*100 if inv_t>0 else 0
        avgp=np.mean([b['model_p'] for b in fb]); acthr=h/n
        print(f"  {lbl} 2-30x: n={n:>5} hit={h:>4} rec={rec:>5.1f}% avgP={avgp:.4f} actHR={acthr:.4f}")

print("="*80)
print("=== 2022+のみウォークフォワード (b=free) ===")
print("="*80)
run_wf(5, 1, 1, "T-1 move_5to1")
run_wf(5, 2, 2, "T-2 move_5to2")
run_wf(5, 3, 3, "T-3 move_5to3")
print("\nDone!")
