# -*- coding: utf-8 -*-
"""v22c: モデルの1着予想精度
三連単「1着固定流し」が有効かどうかの判断材料
"""
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

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

js={}; hh={}; ts_st={}; datasets={}; FNAMES=None
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
    if year<2022: do_update(); continue
    if year not in datasets: datasets[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
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
    for i,h in enumerate(hl):
        ent=entries.get(h,{}); hid=ent.get('hid','')
        f={}
        f['idm_c']=(ent.get('idm') or 50)-avg_idm
        f['rider_c']=(ent.get('rider') or 0)-avg_rider
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
        tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
        f['track_cond']=tc_map.get(tc,0); f['grade']=grade_map.get(grade,0)
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        f['gate_ratio']=h/n
        cw=ent.get('weight') or 0; avg_cw=np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in hl])
        f['weight_c']=(cw-avg_cw) if cw>0 else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        if FNAMES is None: FNAMES=sorted(f.keys())
        datasets[year]['X'].append([f.get(k,0) for k in FNAMES])
        datasets[year]['y'].append(1 if h==winners[0] else 0)
        datasets[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        datasets[year]['meta'].append((rid,h))
        datasets[year]['odds'].append(o3.get(h,0))
    do_update()
for y in datasets:
    d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])

lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

print("\n=== モデルの1着予想精度 ===")
all_results = []
for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in datasets]; fit_yr=test_yr-1
    if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
    X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
    model=lgb.train(lgb_params,lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr),num_boost_round=300)
    X_f=datasets[fit_yr]['X']; y_f=datasets[fit_yr]['y']; init_f=datasets[fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True)
    rd_f=defaultdict(list)
    for i,(rid,hn) in enumerate(datasets[fit_yr]['meta']): rd_f[rid].append(i)
    def neg_ll(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f.items():
            ys=y_f[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
            nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
    bw,tw=res.x

    X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']; init_te=datasets[test_yr]['init']
    meta_te=datasets[test_yr]['meta']; odds_te=datasets[test_yr]['odds']
    raw_te=model.predict(X_te,raw_score=True)
    rd_te=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): rd_te[rid].append(i)

    by_prob = defaultdict(lambda: {'n':0,'win':0,'top3':0})
    total=0; top1_win=0; top1_top3=0; mkt_top1_win=0

    for rid2,idxs in rd_te.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=bw*init_te[idxs]+tw*raw_te[idxs]; s-=s.max()
        probs=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[idx][1] for idx in idxs]
        fps=result_full.get(rid2,{})
        total+=1
        top1_idx=np.argmax(probs); top1_hn=hns[top1_idx]; top1_p=probs[top1_idx]
        top1_fp=fps.get(top1_hn,99)
        if top1_fp==1: top1_win+=1
        if top1_fp<=3: top1_top3+=1
        odds_dict={hns[j]:odds_te[idxs[j]] for j in range(len(hns)) if odds_te[idxs[j]]>0}
        if odds_dict:
            mkt1=min(odds_dict,key=odds_dict.get)
            if fps.get(mkt1,99)==1: mkt_top1_win+=1
        # 確率帯
        if top1_p>=0.5: band='50%+'
        elif top1_p>=0.4: band='40-50%'
        elif top1_p>=0.35: band='35-40%'
        elif top1_p>=0.3: band='30-35%'
        elif top1_p>=0.25: band='25-30%'
        elif top1_p>=0.2: band='20-25%'
        elif top1_p>=0.15: band='15-20%'
        else: band='<15%'
        by_prob[band]['n']+=1
        if top1_fp==1: by_prob[band]['win']+=1
        if top1_fp<=3: by_prob[band]['top3']+=1

        all_results.append({'year':test_yr,'top1_p':float(top1_p),'top1_fp':top1_fp,'band':band})

    print(f"\n  {test_yr}: {total}R")
    print(f"    モデルtop1 → 1着: {top1_win}/{total} ({top1_win/total:.1%})")
    print(f"    モデルtop1 → 3着内: {top1_top3}/{total} ({top1_top3/total:.1%})")
    print(f"    市場1番人気 → 1着: {mkt_top1_win}/{total} ({mkt_top1_win/total:.1%})")
    print(f"    確率帯別:")
    for band in ['50%+','40-50%','35-40%','30-35%','25-30%','20-25%','15-20%','<15%']:
        d=by_prob[band]
        if d['n']==0: continue
        print(f"      {band:>7}: {d['n']:>4}R 1着率={d['win']/d['n']:.1%} 3着内率={d['top3']/d['n']:.1%}")

# 全体集計
print("\n=== 全体（2024-2026）===")
bands = ['50%+','40-50%','35-40%','30-35%','25-30%','20-25%','15-20%','<15%']
print(f"  {'帯':>7} {'n':>5} {'1着率':>7} {'3着内率':>8} | 三連単1着固定が有利な条件: 1着率>33%")
print(f"  {'-'*55}")
for band in bands:
    sub = [r for r in all_results if r['band']==band]
    if not sub: continue
    n=len(sub); win=sum(1 for r in sub if r['top1_fp']==1); t3=sum(1 for r in sub if r['top1_fp']<=3)
    flag = ' *** 三連単有利 ***' if win/n > 0.33 else ''
    print(f"  {band:>7} {n:>5} {win/n:>6.1%} {t3/n:>7.1%}{flag}")

print("\nDone!")
