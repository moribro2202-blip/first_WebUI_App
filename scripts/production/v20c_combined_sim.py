# -*- coding: utf-8 -*-
"""v20c: 単勝 + 1番人気含む馬連 併用シミュレーション
ブートストラップCI + レース単位収支 + 月別累積
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'

# === データロード ===
db = sqlite3.connect(DB, timeout=30)
print("Loading...", flush=True)
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
race_dates = {r[0]: r[1] for r in races_raw}
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
race_cond = {r[0]:r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]:r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
db.close()

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

# === 単勝用データセット ===
print("Building win datasets...", flush=True)
js={}; hh={}; ts_st={}; win_ds={}; FNAMES_W=None
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
    if year not in win_ds: win_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    hl=race_horses.get(rid,[])
    if len(hl)<5: do_update(); continue
    rl=result_cache.get(rid,[])
    if not rl: do_update(); continue
    winners=[r['hn'] for r in rl if r['fp']==1]
    if not winners or winners[0] not in hl: do_update(); continue
    odds_mkt=ts3.get(rid,{})
    if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
    inv=np.array([1/odds_mkt.get(h,999) for h in hl]); s=inv.sum()
    if s==0: do_update(); continue
    mp=inv/s; mp=mp**1.015; mp/=mp.sum()
    o5=ts5.get(rid,{}); o3=ts3.get(rid,{})
    has_move=len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
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
        f['track_cond']=tc_map.get(tc,0); f['grade']=grade_map.get(grade,0)
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        f['gate_ratio']=h/n
        cw=ent.get('weight') or 0; avg_cw=np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in hl])
        f['weight_c']=(cw-avg_cw) if cw>0 else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        if FNAMES_W is None: FNAMES_W=sorted(f.keys())
        win_ds[year]['X'].append([f.get(k,0) for k in FNAMES_W])
        win_ds[year]['y'].append(1 if h==winners[0] else 0)
        win_ds[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        win_ds[year]['meta'].append((rid,h))
        win_ds[year]['odds'].append(o3.get(h,0))
    do_update()
for y in win_ds:
    d=win_ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])

# === 馬連ペアデータセット ===
print("Building umaren pair datasets...", flush=True)
# horse_features再構築（do_updateで更新済みのjs/hh/ts_stを使う）
# → 上のループで既にdo_update済みなのでhorse_featuresは不要
# ペア特徴量はv20と同じ構造
PAIR_FNAMES=None; um_ds={}
cdb=sqlite3.connect(DB,timeout=30)

# horse_features を再構築（js/hh/ts_stは既に2026まで更新済み）
# 2022+のレースで特徴量を再計算
js2={}; hh2={}; ts_st2={}
for rid,rd,vc,sf,dt in races_raw:
    year=int(rd[:4])
    def do_update2():
        for res in result_cache.get(rid,[]):
            hn,fp,hid=res['hn'],res['fp'],res['hid']
            ent=entry_cache.get(rid,{}).get(hn,{})
            jn=ent.get('jockey',''); tn=ent.get('trainer','')
            if jn:
                if jn not in js2: js2[jn]={'r':0,'w':0,'t3':0}
                js2[jn]['r']+=1
                if fp==1: js2[jn]['w']+=1
                if fp<=3: js2[jn]['t3']+=1
            if tn:
                if tn not in ts_st2: ts_st2[tn]={'r':0,'w':0,'t3':0}
                ts_st2[tn]['r']+=1
                if fp==1: ts_st2[tn]['w']+=1
                if fp<=3: ts_st2[tn]['t3']+=1
            if hid:
                if hid not in hh2: hh2[hid]=[]
                hh2[hid].append({'fp':fp,'dist':dt,'surface':sf})
                if len(hh2[hid])>30: hh2[hid]=hh2[hid][-30:]
    if year<2022: do_update2(); continue
    hl=race_horses.get(rid,[])
    if len(hl)<5: do_update2(); continue

    odds_mkt=ts3.get(rid,{}); o5=ts5.get(rid,{}); o3=ts3.get(rid,{})
    if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
    has_move=len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
    entries=entry_cache.get(rid,{}); n=len(hl)
    idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
    riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
    ozd=oz_cache.get(rid,{}); mkt_d=odds_mkt
    oz_inv2={h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
    mk_inv2={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
    oz_sum2=sum(oz_inv2.values()) or 1; mk_sum2=sum(mk_inv2.values()) or 1
    cyb_scores=[cyb_cache.get((rid,h),0) for h in hl]
    avg_cyb=np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0

    # confirmed_odds
    co={}
    for row in cdb.execute("SELECT combination,odds FROM confirmed_odds WHERE race_id=? AND bet_type='umaren' AND odds>0",(rid,)).fetchall():
        co[row[0]]=row[1]
    if len(co)<3: do_update2(); continue
    inv_um={k:1.0/v for k,v in co.items()}; total_inv=sum(inv_um.values())
    if total_inv==0: do_update2(); continue
    mkt_prob={k:v/total_inv for k,v in inv_um.items()}
    top2=sorted([r for r in result_cache.get(rid,[]) if r['fp'] in (1,2)],key=lambda x:x['fp'])
    if len(top2)<2: do_update2(); continue
    winner_combo='-'.join(str(x) for x in sorted([top2[0]['hn'],top2[1]['hn']]))

    if year not in um_ds: um_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
    sorted_h=sorted(o3.items(),key=lambda x:x[1]) if o3 else []
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}

    for combo,odds_val in co.items():
        parts=combo.split('-')
        if len(parts)!=2: continue
        try: h1,h2=int(parts[0]),int(parts[1])
        except: continue
        # 1番人気含むフィルタ
        pop_high=min(rank_map.get(h1,99),rank_map.get(h2,99))

        # ペア特徴量
        feats_h = {}
        for h in [h1,h2]:
            ent=entries.get(h,{}); hid=ent.get('hid','')
            f={}
            f['idm_c']=(ent.get('idm') or 50)-avg_idm
            f['rider_c']=(ent.get('rider') or 0)-avg_rider
            f['total_index']=ent.get('total') or 0
            oz_p=oz_inv2.get(h,0)/oz_sum2; mk_p=mk_inv2.get(h,0)/mk_sum2
            f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
            f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
            jn=ent.get('jockey',''); tn=ent.get('trainer','')
            jst2=js2.get(jn,{}); f['jockey_t3rate']=jst2.get('t3',0)/jst2['r'] if jst2.get('r',0)>=30 else -1
            tst2=ts_st2.get(tn,{}); f['trainer_t3rate']=tst2.get('t3',0)/tst2['r'] if tst2.get('r',0)>=30 else -1
            runs=hh2.get(hid,[])
            f['horse_runs']=len(runs)
            if runs:
                rc=runs[-5:]; f['avg_fp_5']=np.mean([r['fp'] for r in rc])
                f['top3_rate']=sum(1 for r in runs if r['fp']<=3)/len(runs)
                f['last_fp']=runs[-1]['fp']
                f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
            else:
                f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
            f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
            if has_move:
                oo5=o5.get(h,0); oo3=o3.get(h,0)
                f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
            else: f['move_5to3']=0
            f['win_odds_3min']=o3.get(h,0)
            feats_h[h]=f

        if h1 not in feats_h or h2 not in feats_h: continue
        f1=feats_h[h1]; f2=feats_h[h2]
        pf={}
        for key in ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']:
            v1=f1.get(key,0); v2=f2.get(key,0)
            pf[f'{key}_sum']=v1+v2; pf[f'{key}_diff']=abs(v1-v2)
        ow1=f1.get('win_odds_3min',0); ow2=f2.get('win_odds_3min',0)
        pf['win_odds_ratio']=min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
        pf['win_odds_sum_inv']=(1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
        if PAIR_FNAMES is None: PAIR_FNAMES=sorted(pf.keys())
        mp_val=mkt_prob.get(combo,1e-8)
        init=math.log(max(mp_val,1e-15))-math.log(max(1-mp_val,1e-15))
        is_hit=1 if combo==winner_combo else 0
        um_ds[year]['X'].append([pf.get(k,0) for k in PAIR_FNAMES])
        um_ds[year]['y'].append(is_hit)
        um_ds[year]['init'].append(init)
        um_ds[year]['meta'].append((rid,combo))
        um_ds[year]['odds'].append(odds_val)
        um_ds[year]['pop'].append(pop_high)
    do_update2()
cdb.close()

for y in um_ds:
    d=um_ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds']); d['pop']=np.array(d['pop'])
    print(f"  um {y}: {len(d['X']):,}")
for y in win_ds:
    print(f"  win {y}: {len(win_ds[y]['X']):,}")

# === WF ===
lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_u={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

print("\nRunning WF...", flush=True)
win_bets=[]; um_bets=[]
BET=100

for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr)]
    fit_yr=test_yr-1

    # --- 単勝 ---
    if all(y in win_ds for y in train_yrs) and fit_yr in win_ds and test_yr in win_ds:
        X_tr=np.vstack([win_ds[y]['X'] for y in train_yrs]); y_tr=np.concatenate([win_ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([win_ds[y]['init'] for y in train_yrs])
        model_w=lgb.train(lgb_w,lgb.Dataset(X_tr,y_tr,feature_name=FNAMES_W,init_score=init_tr),num_boost_round=300)
        X_f=win_ds[fit_yr]['X']; y_f=win_ds[fit_yr]['y']; init_f=win_ds[fit_yr]['init']
        raw_f=model_w.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,hn) in enumerate(win_ds[fit_yr]['meta']): rd_f[rid].append(i)
        def neg_ll_w(p):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res_w=minimize(neg_ll_w,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        bw,tw=res_w.x
        X_te=win_ds[test_yr]['X']; y_te=win_ds[test_yr]['y']; init_te=win_ds[test_yr]['init']
        meta_te=win_ds[test_yr]['meta']; odds_te=win_ds[test_yr]['odds']
        raw_te=model_w.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_te): rd_te[rid].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=bw*init_te[idxs]+tw*raw_te[idxs]; s-=s.max(); probs=np.exp(s)/np.exp(s).sum()
            winner=meta_te[idxs[wi[0]]][1]
            for j,idx in enumerate(idxs):
                hn=meta_te[idx][1]; o=odds_te[idx]
                if not(2<=o<=40): continue
                ev=probs[j]*o
                if ev<1.2: continue
                is_hit=int(hn==winner)
                payout=hjc_all.get(rid2,{}).get('win_hjc',{}).get(str(hn),0) if is_hit else 0
                rd=race_dates.get(rid2,''); month=rd[:7]
                win_bets.append({'year':test_yr,'rid':rid2,'month':month,'ev':ev,'is_hit':is_hit,'payout':payout,'type':'win'})
        print(f"  {test_yr} win: b={bw:.3f} tau={tw:.3f}")

    # --- 馬連 ---
    if all(y in um_ds for y in train_yrs) and fit_yr in um_ds and test_yr in um_ds:
        X_tr=np.vstack([um_ds[y]['X'] for y in train_yrs]); y_tr=np.concatenate([um_ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([um_ds[y]['init'] for y in train_yrs])
        model_u=lgb.train(lgb_u,lgb.Dataset(X_tr,y_tr,feature_name=PAIR_FNAMES,init_score=init_tr),num_boost_round=300)
        X_f=um_ds[fit_yr]['X']; y_f=um_ds[fit_yr]['y']; init_f=um_ds[fit_yr]['init']
        raw_f=model_u.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,combo) in enumerate(um_ds[fit_yr]['meta']): rd_f[rid].append(i)
        def neg_ll_u(p):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res_u=minimize(neg_ll_u,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        bu,tu=res_u.x
        X_te=um_ds[test_yr]['X']; y_te=um_ds[test_yr]['y']; init_te=um_ds[test_yr]['init']
        meta_te=um_ds[test_yr]['meta']; odds_te=um_ds[test_yr]['odds']; pop_te=um_ds[test_yr]['pop']
        raw_te=model_u.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,combo) in enumerate(meta_te): rd_te[rid].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=bu*init_te[idxs]+tu*raw_te[idxs]; s-=s.max(); probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                if pop_te[idx]>1: continue  # 1番人気含むのみ
                combo=meta_te[idx][1]; o=odds_te[idx]; ev=probs[j]*o
                if ev<1.2: continue
                is_hit=y_te[idx]
                payout=hjc_all.get(rid2,{}).get('umaren_hjc',{}).get(combo,0) if is_hit else 0
                rd=race_dates.get(rid2,''); month=rd[:7]
                um_bets.append({'year':test_yr,'rid':rid2,'month':month,'ev':ev,'is_hit':int(is_hit),'payout':payout,'type':'umaren'})
        print(f"  {test_yr} um: b={bu:.3f} tau={tu:.3f}")

print(f"\n  win bets: {len(win_bets):,}, umaren bets: {len(um_bets):,}")

# === 結果 ===
all_combined = win_bets + um_bets

print(f"\n{'='*90}")
print("v20c: 単勝 + 1番人気馬連 併用シミュレーション（EV>=1.2、1点100円）")
print(f"{'='*90}")

for label, data in [('単勝のみ',win_bets),('1番人気馬連のみ',um_bets),('併用（単勝+馬連）',all_combined)]:
    if not data: continue
    n=len(data); hits=sum(d['is_hit'] for d in data)
    inv=n*BET; pay=sum(d['payout']*BET for d in data if d['is_hit']); rec=pay/inv*100; pnl=pay-inv
    print(f"\n  {label}:")
    print(f"    n={n:,} 的中={hits} ({hits/n:.1%}) 投資={inv:,}円 払戻={pay:,.0f}円 回収率={rec:.1f}% PnL={pnl:+,.0f}円")
    for yr in [2024,2025,2026]:
        ys=[d for d in data if d['year']==yr]
        if not ys: continue
        yn=len(ys); yh=sum(d['is_hit'] for d in ys)
        yi=yn*BET; yp=sum(d['payout']*BET for d in ys if d['is_hit']); yr_rec=yp/yi*100
        print(f"    {yr}: n={yn:,} 的中={yh} ({yh/yn:.1%}) rec={yr_rec:.1f}% PnL={yp-yi:+,.0f}円")

# レース単位
print(f"\n--- レース単位の的中率 ---")
for label, data in [('単勝のみ',win_bets),('1番人気馬連のみ',um_bets),('併用',all_combined)]:
    if not data: continue
    by_race=defaultdict(lambda:{'inv':0,'pay':0,'has_hit':False})
    for d in data:
        r=by_race[d['rid']]
        r['inv']+=BET; r['pay']+=d['payout']*BET if d['is_hit'] else 0
        r['has_hit']=r['has_hit'] or d['is_hit']
    races=list(by_race.values())
    hit_r=sum(1 for r in races if r['has_hit'])
    print(f"  {label}: {len(races)}R 的中{hit_r}R ({hit_r/len(races):.1%}) 平均投資/R={np.mean([r['inv'] for r in races]):.0f}円")

# 月別累積損益
print(f"\n--- 月別累積損益（併用） ---")
months=sorted(set(d['month'] for d in all_combined if d['month']))
cum_pnl=0
print(f"  {'月':>7} {'n':>5} {'的中':>4} {'投資':>8} {'払戻':>8} {'月PnL':>8} {'累積PnL':>9}")
for m in months:
    sub=[d for d in all_combined if d['month']==m]
    n=len(sub); hits=sum(d['is_hit'] for d in sub)
    inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit'])
    pnl=pay-inv; cum_pnl+=pnl
    print(f"  {m:>7} {n:>5} {hits:>4} {inv:>7,} {pay:>7,.0f} {pnl:>+7,.0f} {cum_pnl:>+8,.0f}")

# ブートストラップCI
print(f"\n--- ブートストラップCI（5000回）---")
for label, data in [('単勝のみ',win_bets),('1番人気馬連のみ',um_bets),('併用',all_combined)]:
    if len(data)<50: continue
    by_race=defaultdict(list)
    for d in data: by_race[d['rid']].append(d)
    rids=list(by_race.keys())
    np.random.seed(42); br=[]
    for _ in range(5000):
        samp=np.random.choice(rids,size=len(rids),replace=True)
        si=0; sp=0
        for r in samp:
            for d in by_race[r]: si+=BET; sp+=d['payout']*BET if d['is_hit'] else 0
        if si>0: br.append(sp/si*100)
    br.sort()
    inv=len(data)*BET; pay=sum(d['payout']*BET for d in data if d['is_hit'])
    print(f"  {label}: n={len(data):,} rec={pay/inv*100:.1f}% 95%CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

print("\nDone!")
