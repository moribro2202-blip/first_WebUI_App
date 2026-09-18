# -*- coding: utf-8 -*-
"""v22e: 全券種シミュレーション — 券種自動選択
各レースで最適な券種を選択し、1R予算1000円で投資した場合の成績
2024-2026 WF、推定オッズでEV判定、HJC確定で払戻
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations, permutations
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
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
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
TAKEOUT = {'win':0.20,'umaren':0.225,'sanrenpuku':0.25,'sanrentan':0.2725,'umatan':0.225}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_full(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    umaren=defaultdict(float); trio=defaultdict(float); trifecta={}; umatan={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+=pij; umatan[(i,j)]=pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                trio[tuple(sorted([i,j,k]))]+=pijk; trifecta[(i,j,k)]=pijk
    return umaren, umatan, trio, trifecta

# 単勝WFモデル構築
print("Building datasets...", flush=True)
js={}; hh={}; ts_st={}; win_ds={}; WFNAMES=None; trio_ds={}; TRFNAMES=None

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
    tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
    fps=result_full.get(rid,{}); month=rd[:7]

    if year not in win_ds: win_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    feats_h={}
    for i,h in enumerate(hl):
        ent=entries.get(h,{}); hid=ent.get('hid','')
        f={}
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
        else:
            f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        f['win_odds_3min']=o3.get(h,0)
        feats_h[h]=f
        if WFNAMES is None: WFNAMES=sorted([k for k in FEAT_KEYS])
        win_ds[year]['X'].append([f.get(k,0) for k in WFNAMES])
        win_ds[year]['y'].append(1 if h==winners[0] else 0)
        win_ds[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        win_ds[year]['meta'].append((rid,h))
        win_ds[year]['odds'].append(o3.get(h,0))

    # 三連複データセット
    trio_mkt_sh = defaultdict(float)
    p2=mp**LAM2; p3=mp**LAM3; S1=mp.sum(); S2=p2.sum(); S3=p3.sum()
    for i in range(len(hl)):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(len(hl)):
            if j==i: continue
            pij=(mp[i]/S1)*(p2[j]/d2); d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(len(hl)):
                if k in (i,j): continue
                trio_mkt_sh[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    top8=[h for h,_ in sorted_h[:8]]
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    if len(top3_fps)>=3:
        winner_tr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in trio_ds: trio_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
        for a,b,c in combinations(top8,3):
            ai=hl.index(a); bi=hl.index(b); ci=hl.index(c)
            key=tuple(sorted([ai,bi,ci])); sh_p=trio_mkt_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c]))
            pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
            for k in FEAT_KEYS:
                v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
            odds_list=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
            pf['win_odds_top_ratio']=odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
            pf['win_odds_sum_inv']=sum(1/o for o in odds_list if o>0)
            if TRFNAMES is None: TRFNAMES=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_tr else 0
            est_odds=(1/sh_p)*(1-TAKEOUT['sanrenpuku'])
            trio_ds[year]['X'].append([pf.get(k,0) for k in TRFNAMES])
            trio_ds[year]['y'].append(is_hit); trio_ds[year]['init'].append(init)
            trio_ds[year]['meta'].append((rid,combo)); trio_ds[year]['odds'].append(est_odds)
    do_update()

for ds_name, ds_obj in [('win',win_ds),('trio',trio_ds)]:
    for y in sorted(ds_obj.keys()):
        d=ds_obj[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
    sizes=', '.join(str(y)+':'+str(len(ds_obj[y]['X'])) for y in sorted(ds_obj.keys()))
    print(f"  {ds_name}: {sizes}")

lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_t={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

BUDGET = 1000
print("\nWF + auto-select...", flush=True)
race_bets = []  # per-race results

for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr)]; fit_yr=test_yr-1
    if fit_yr not in win_ds or test_yr not in win_ds: continue

    # 単勝モデル
    X_tr=np.vstack([win_ds[y]['X'] for y in train_yrs if y in win_ds])
    y_tr=np.concatenate([win_ds[y]['y'] for y in train_yrs if y in win_ds])
    init_tr=np.concatenate([win_ds[y]['init'] for y in train_yrs if y in win_ds])
    wm=lgb.train(lgb_w,lgb.Dataset(X_tr,y_tr,feature_name=WFNAMES,init_score=init_tr),num_boost_round=300)
    X_f=win_ds[fit_yr]['X']; y_f=win_ds[fit_yr]['y']; init_f=win_ds[fit_yr]['init']
    raw_f=wm.predict(X_f,raw_score=True)
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

    # 三連複モデル
    X_tr_t=np.vstack([trio_ds[y]['X'] for y in train_yrs if y in trio_ds])
    y_tr_t=np.concatenate([trio_ds[y]['y'] for y in train_yrs if y in trio_ds])
    init_tr_t=np.concatenate([trio_ds[y]['init'] for y in train_yrs if y in trio_ds])
    tm=lgb.train(lgb_t,lgb.Dataset(X_tr_t,y_tr_t,feature_name=TRFNAMES,init_score=init_tr_t),num_boost_round=300)
    X_f_t=trio_ds[fit_yr]['X']; y_f_t=trio_ds[fit_yr]['y']; init_f_t=trio_ds[fit_yr]['init']
    raw_f_t=tm.predict(X_f_t,raw_score=True)
    rd_f_t=defaultdict(list)
    for i,(rid,combo) in enumerate(trio_ds[fit_yr]['meta']): rd_f_t[rid].append(i)
    def neg_ll_t(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f_t.items():
            ys=y_f_t[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f_t[idxs]+tau*raw_f_t[idxs]; s-=s.max()
            nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res_t=minimize(neg_ll_t,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
    bt,tt=res_t.x
    print(f"  {test_yr}: win b={bw:.3f} tau={tw:.3f} | trio b={bt:.3f} tau={tt:.3f}")

    # テスト年: レースごとに券種選択
    X_te=win_ds[test_yr]['X']; y_te=win_ds[test_yr]['y']; init_te=win_ds[test_yr]['init']
    meta_te=win_ds[test_yr]['meta']; odds_te=win_ds[test_yr]['odds']
    raw_te=wm.predict(X_te,raw_score=True)
    rd_te=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): rd_te[rid].append(i)

    X_te_t=trio_ds[test_yr]['X']; y_te_t=trio_ds[test_yr]['y']; init_te_t=trio_ds[test_yr]['init']
    meta_te_t=trio_ds[test_yr]['meta']; odds_te_t=trio_ds[test_yr]['odds']
    raw_te_t=tm.predict(X_te_t,raw_score=True)
    rd_te_t=defaultdict(list)
    for i,(rid,combo) in enumerate(meta_te_t): rd_te_t[rid].append(i)

    for rid2, idxs in rd_te.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=bw*init_te[idxs]+tw*raw_te[idxs]; s-=s.max()
        probs_win=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[idx][1] for idx in idxs]
        fps=result_full.get(rid2,{})
        hjc=hjc_all.get(rid2,{})
        month=race_dates.get(rid2,'')[:7]
        winner=hns[wi[0]]

        # 単勝候補
        win_cands=[]
        for j in range(len(hns)):
            o=odds_te[idxs[j]]
            if not(2<=o<=40): continue
            ev=probs_win[j]*o
            if ev>=1.2:
                is_hit=int(hns[j]==winner)
                payout=hjc.get('win_hjc',{}).get(str(hns[j]),0) if is_hit else 0
                win_cands.append({'ev':ev,'payout':payout,'is_hit':is_hit,'type':'win'})

        # 三連複候補
        trio_cands=[]
        if rid2 in rd_te_t:
            tidxs=rd_te_t[rid2]
            ys_t=y_te_t[tidxs]; wi_t=np.where(ys_t==1)[0]
            if len(wi_t)>0:
                s_t=bt*init_te_t[tidxs]+tt*raw_te_t[tidxs]; s_t-=s_t.max()
                probs_trio=np.exp(s_t)/np.exp(s_t).sum()
                for j,idx in enumerate(tidxs):
                    est_odds=odds_te_t[idx]
                    ev=probs_trio[j]*est_odds
                    if ev>=1.2:
                        combo=meta_te_t[idx][1]
                        is_hit=y_te_t[idx]
                        payout=hjc.get('sanrenpuku_hjc',{}).get(combo,0) if is_hit else 0
                        trio_cands.append({'ev':ev,'payout':payout,'is_hit':int(is_hit),'type':'sanrenpuku','combo':combo})

        # 券種選択: 期待利益が大きい方
        def calc_profit(cands, budget):
            if not cands: return -999, 0, 0
            n=len(cands); per=max(100,(budget//n//100)*100)
            invest=n*per; exp_pay=sum(c['ev']*per for c in cands)
            return exp_pay-invest, invest, per

        wp, wi_val, wper = calc_profit(win_cands, BUDGET)
        tp, ti_val, tper = calc_profit(trio_cands, BUDGET)

        if tp > wp and trio_cands:
            chosen='sanrenpuku'; cands=trio_cands; invest=ti_val; per=tper
        elif win_cands:
            chosen='win'; cands=win_cands; invest=wi_val; per=wper
        else:
            continue  # 見送り

        n_bets=len(cands)
        payout=sum(c['payout']*per for c in cands if c['is_hit'])
        has_hit=any(c['is_hit'] for c in cands)
        race_bets.append({'year':test_yr,'rid':rid2,'type':chosen,'n_bets':n_bets,
                          'invest':invest,'payout':payout,'hit':has_hit,'month':month,
                          'win_cands':len(win_cands),'trio_cands':len(trio_cands),
                          'top1_p':float(max(probs_win))})

# === 結果 ===
BT_JP={'win':'単勝','sanrenpuku':'三連複','umaren':'馬連'}
print(f"\n{'='*80}")
print("v22e: 券種自動選択シミュレーション（1R={BUDGET}円）")
print(f"{'='*80}")

total_inv=sum(r['invest'] for r in race_bets)
total_pay=sum(r['payout'] for r in race_bets)
hit_r=sum(1 for r in race_bets if r['hit'])
print(f"\n全体: {len(race_bets)}R 投資{total_inv:,}円 払戻{total_pay:,.0f}円 回収率{total_pay/total_inv*100:.1f}% 的中{hit_r}R ({hit_r/len(race_bets):.1%})")

# 年別
for yr in [2024,2025,2026]:
    sub=[r for r in race_bets if r['year']==yr]
    if not sub: continue
    inv=sum(r['invest'] for r in sub); pay=sum(r['payout'] for r in sub)
    hits=sum(1 for r in sub if r['hit'])
    print(f"  {yr}: {len(sub)}R inv={inv:,} pay={pay:,.0f} rec={pay/inv*100:.1f}% hit={hits}R")

# 券種別
print(f"\n--- 券種別 ---")
by_type=defaultdict(lambda:{'n':0,'invest':0,'payout':0,'hits':0})
for r in race_bets:
    t=by_type[r['type']]; t['n']+=1; t['invest']+=r['invest']; t['payout']+=r['payout']
    if r['hit']: t['hits']+=1
for bt in sorted(by_type.keys()):
    d=by_type[bt]; rec=d['payout']/d['invest']*100 if d['invest']>0 else 0
    print(f"  {BT_JP.get(bt,bt)}: {d['n']}R inv={d['invest']:,} pay={d['payout']:,.0f} rec={rec:.1f}% hit={d['hits']}R ({d['hits']/d['n']:.1%})")

# 月別累積
print(f"\n--- 月別累積 ---")
months=sorted(set(r['month'] for r in race_bets))
cum=0
for m in months:
    sub=[r for r in race_bets if r['month']==m]
    inv=sum(r['invest'] for r in sub); pay=sum(r['payout'] for r in sub)
    pnl=pay-inv; cum+=pnl
    print(f"  {m} {len(sub):>3}R inv={inv:>6,} PnL={pnl:>+7,.0f} cum={cum:>+8,.0f}")

# 比較: 単勝のみ / 三連複のみ / 自動選択
print(f"\n--- 比較: 戦略別 ---")
# 単勝のみ（自動選択で単勝が選ばれたレース + 三連複レースでも単勝があれば）
# → 単純に単勝EV>=1.2のみ
win_only_inv=0; win_only_pay=0; win_only_n=0
trio_only_inv=0; trio_only_pay=0; trio_only_n=0
for r in race_bets:
    if r['win_cands']>0:
        # 単勝のみの場合
        pass  # 詳細データがないので近似
for r in race_bets:
    if r['type']=='win':
        win_only_inv+=r['invest']; win_only_pay+=r['payout']; win_only_n+=1
    elif r['type']=='sanrenpuku':
        trio_only_inv+=r['invest']; trio_only_pay+=r['payout']; trio_only_n+=1

auto_inv=total_inv; auto_pay=total_pay
print(f"  自動選択: {len(race_bets)}R inv={auto_inv:,} rec={auto_pay/auto_inv*100:.1f}% PnL={auto_pay-auto_inv:+,.0f}")
if win_only_inv>0:
    print(f"   (単勝分): {win_only_n}R inv={win_only_inv:,} rec={win_only_pay/win_only_inv*100:.1f}%")
if trio_only_inv>0:
    print(f"   (三連複分): {trio_only_n}R inv={trio_only_inv:,} rec={trio_only_pay/trio_only_inv*100:.1f}%")

print("\nDone!")
