# -*- coding: utf-8 -*-
"""v16全券種×年別シミュレーション
move_5to3, cyb_c, 較正, Stern-Harville, 2022+WF
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations
from scipy.optimize import minimize
from sklearn.linear_model import LogisticRegression
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
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
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

LAM2, LAM3 = 0.8076, 0.6978
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

def stern_harville(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    place=np.zeros(n); wide=defaultdict(float); umaren=defaultdict(float); trio=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+= pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                place[i]+=pijk; place[j]+=pijk; place[k]+=pijk
                for a,b in combinations(sorted([i,j,k]),2): wide[(a,b)]+=pijk
                trio[tuple(sorted([i,j,k]))]+=pijk
    return place, wide, umaren, trio

print("Loaded.", flush=True)

# データセット構築（v16_backtest.pyと同じ、省略せず全部）
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
    if year not in datasets:
        datasets[year]={'X':[],'y':[],'init':[],'meta':[],'odds_3min':[]}
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
                o5=ts5.get(rid,{}); o3=ts3.get(rid,{})
                has_move=len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
                entries=entry_cache.get(rid,{}); n=len(hl)
                tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
                idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
                riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
                oz=oz_cache.get(rid,{}); mkt_d=odds_mkt
                oz_inv={h:1/oz[h] if h in oz and oz[h]>0 else 0 for h in hl}
                mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
                oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
                cyb_scores=[cyb_cache.get((rid,h),0) for h in hl]
                avg_cyb=np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0
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
                    f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
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
                        oo5=o5.get(h,0); oo3=o3.get(h,0)
                        f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
                    else: f['move_5to3']=0
                    if FNAMES is None: FNAMES=sorted(f.keys())
                    datasets[year]['X'].append([f.get(k,0) for k in FNAMES])
                    datasets[year]['y'].append(1 if h==winners[0] else 0)
                    p_val=mp[i]
                    datasets[year]['init'].append(math.log(max(p_val,1e-15))-math.log(max(1-p_val,1e-15)))
                    datasets[year]['meta'].append((rid,h))
                    datasets[year]['odds_3min'].append(o3.get(h,0))
    do_update()

for y in sorted(datasets.keys()):
    d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds_3min']=np.array(d['odds_3min'])
    print(f"  {y}: {len(d['X']):,}")

lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

# WF + 較正 + 全券種
print("\nRunning WF...", flush=True)
bets = {'win':[],'place':[],'umaren':[],'wide':[],'trio':[]}

for test_yr in [2024, 2025, 2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in datasets]
    fit_yr=test_yr-1
    if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
    X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
    dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr)
    model=lgb.train(lgb_params,dtrain,num_boost_round=300)

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
    # 較正
    cal_p=[]; cal_y=[]
    for rid2,idxs in rd_f.items():
        ys=y_f[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_f[idxs]+tau_use*raw_f[idxs]; s-=s.max(); tp=np.exp(s)/np.exp(s).sum()
        for j,idx in enumerate(idxs): cal_p.append(tp[j]); cal_y.append(y_f[idx])
    cal_p=np.array(cal_p); cal_y=np.array(cal_y)
    lp=np.log(np.clip(cal_p,1e-8,1-1e-8)/(1-np.clip(cal_p,1e-8,1-1e-8)))
    Xc=np.column_stack([lp,lp**2])
    cal_model=LogisticRegression(C=1e6,max_iter=1000).fit(Xc,cal_y)
    print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}", flush=True)

    # テスト年
    X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']
    init_te=datasets[test_yr]['init']; meta_te=datasets[test_yr]['meta']
    odds_te=datasets[test_yr]['odds_3min']
    raw_te=model.predict(X_te,raw_score=True)
    race_data=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): race_data[rid].append(i)

    for rid2,idxs in race_data.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        hns=[meta_te[i][1] for i in idxs]
        fps=result_full.get(rid2,{})
        hjc=hjc_all.get(rid2,{})
        # モデル確率+較正
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max(); p_raw=np.exp(s)/np.exp(s).sum()
        lp2=np.log(np.clip(p_raw,1e-8,1-1e-8)/(1-np.clip(p_raw,1e-8,1-1e-8)))
        Xc2=np.column_stack([lp2,lp2**2])
        p_cal=cal_model.predict_proba(Xc2)[:,1]; p_cal=p_cal/p_cal.sum()
        # Stern-Harville
        place_p, wide_p, umaren_p, trio_p = stern_harville(p_cal)

        winner=hns[wi[0]]
        # 単勝
        for j,idx in enumerate(idxs):
            o=odds_te[idx]
            if o<=0: continue
            is_hit=int(hns[j]==winner)
            payout=hjc.get('win_hjc',{}).get(str(hns[j]),0) if is_hit else 0
            bets['win'].append({'year':test_yr,'ev':float(p_cal[j]*o),'is_hit':is_hit,'payout':payout,'odds':o,'p':float(p_cal[j])})
        # 複勝
        for j,idx in enumerate(idxs):
            fp=fps.get(hns[j],99); is_place=int(fp<=3)
            payout=hjc.get('place_hjc',{}).get(str(hns[j]),0) if is_place else 0
            est_odds=(1/place_p[j]*0.8) if place_p[j]>0.01 else 0
            bets['place'].append({'year':test_yr,'ev':float(place_p[j]*est_odds),'is_hit':is_place,'payout':payout,'p':float(place_p[j])})
        # 馬連（上位2頭）
        top2=np.argsort(p_cal)[::-1][:2]
        h1,h2=hns[top2[0]],hns[top2[1]]
        um_p=umaren_p.get(tuple(sorted([top2[0],top2[1]])),0)
        fp1,fp2=fps.get(h1,99),fps.get(h2,99)
        is_hit=int(set([fp1,fp2])==set([1,2]))
        combo='-'.join(str(x) for x in sorted([h1,h2]))
        payout=hjc.get('umaren_hjc',{}).get(combo,0) if is_hit else 0
        est_odds=(1/um_p*0.775) if um_p>0.001 else 0
        bets['umaren'].append({'year':test_yr,'ev':float(um_p*est_odds),'is_hit':is_hit,'payout':payout,'p':float(um_p)})
        # ワイド（上位2頭）
        w_p=wide_p.get(tuple(sorted([top2[0],top2[1]])),0)
        is_hit_w=int(fp1<=3 and fp2<=3)
        payout_w=hjc.get('wide_hjc',{}).get(combo,0) if is_hit_w else 0
        est_odds_w=(1/w_p*0.75) if w_p>0.001 else 0
        bets['wide'].append({'year':test_yr,'ev':float(w_p*est_odds_w),'is_hit':is_hit_w,'payout':payout_w,'p':float(w_p)})
        # 三連複（上位3頭）
        top3=np.argsort(p_cal)[::-1][:3]
        h1t,h2t,h3t=hns[top3[0]],hns[top3[1]],hns[top3[2]]
        tr_p=trio_p.get(tuple(sorted([top3[0],top3[1],top3[2]])),0)
        fps3=set([fps.get(h1t,99),fps.get(h2t,99),fps.get(h3t,99)])
        is_hit_t=int(fps3==set([1,2,3]))
        combo3='-'.join(str(x) for x in sorted([h1t,h2t,h3t]))
        payout_t=hjc.get('sanrenpuku_hjc',{}).get(combo3,0) if is_hit_t else 0
        est_odds_t=(1/tr_p*0.75) if tr_p>0.001 else 0
        bets['trio'].append({'year':test_yr,'ev':float(tr_p*est_odds_t),'is_hit':is_hit_t,'payout':payout_t,'p':float(tr_p)})

# === 結果 ===
print(f"\n{'='*90}")
print("v16全券種×年別（較正+Stern-Harville、2024-2026）")
print(f"{'='*90}")

for bt, label in [('win','単勝（全馬）'),('place','複勝（全馬）'),('umaren','馬連（上位2頭）'),('wide','ワイド（上位2頭）'),('trio','三連複（上位3頭）')]:
    data = bets[bt]
    total_n=len(data); total_hits=sum(d['is_hit'] for d in data)
    total_inv=total_n*100; total_pay=sum(d['payout']*100 for d in data if d['is_hit'])
    total_rec=total_pay/total_inv*100 if total_inv>0 else 0
    avg_p=np.mean([d['p'] for d in data]); avg_hit=np.mean([d['is_hit'] for d in data])
    ratio=avg_hit/avg_p if avg_p>0 else 0

    print(f"\n■ {label} (n={total_n:,} 回収率={total_rec:.1f}% 予測P={avg_p:.4f} 実績={avg_hit:.4f} 比={ratio:.2f})")
    print(f"  {'年':>4} {'n':>7} {'的中':>5} {'的中率':>7} {'投資':>10} {'HJC払戻':>10} {'回収率':>7} {'予測P':>7} {'比':>5}")
    print(f"  {'-'*70}")
    for yr in [2024, 2025, 2026]:
        sub=[d for d in data if d['year']==yr]
        if not sub: continue
        n=len(sub); hits=sum(d['is_hit'] for d in sub)
        inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
        rec=pay/inv*100 if inv>0 else 0
        ap=np.mean([d['p'] for d in sub]); ah=np.mean([d['is_hit'] for d in sub])
        r=ah/ap if ap>0 else 0
        print(f"  {yr:>4} {n:>7} {hits:>5} {ah:>6.3%} {inv:>9,}円 {pay:>9,.0f}円 {rec:>6.1f}% {ap:>6.4f} {r:>4.2f}")

print("\nDone!")
