# -*- coding: utf-8 -*-
"""v18: 馬連の深掘り分析
- 年×EV帯別
- プールオッズ帯別
- モデル確率ランク別
- 月別（2026年）
- 上位N頭の組合せ比較
- キャリブレーション（予測vs実績）
- ブートストラップCI
- 1年50%ルールチェック
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import combinations
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
conf_odds = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM confirmed_odds WHERE odds>0 AND bet_type='umaren'").fetchall():
    conf_odds[row[0]][row[1]][row[2]] = row[3]
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
db.close()
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

def stern_harville_umaren(p):
    n=len(p); p2=p**LAM2
    S1=p.sum(); S2=p2.sum()
    umaren=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+=pij
    return umaren

# データセット構築
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
for y in sorted(datasets.keys()):
    d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
    print(f"  {y}: {len(d['X']):,}")

lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

# WF
print("\nRunning WF...", flush=True)
all_bets = []  # 馬連全組合せ
all_bets_win = []  # 単勝（参考）

for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in datasets]
    fit_yr=test_yr-1
    if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
    X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
    dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr)
    model=lgb.train(lgb_params,dtrain,num_boost_round=300)
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
    print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")

    X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']; init_te=datasets[test_yr]['init']
    meta_te=datasets[test_yr]['meta']; odds_te=datasets[test_yr]['odds']
    raw_te=model.predict(X_te,raw_score=True)
    race_data=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): race_data[rid].append(i)

    for rid2,idxs in race_data.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
        p_raw=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[i][1] for i in idxs]
        fps=result_full.get(rid2,{})
        hjc=hjc_all.get(rid2,{})
        rd_str=race_dates.get(rid2,'')
        month=rd_str[:7] if rd_str else ''
        umaren_p=stern_harville_umaren(p_raw)
        co_umaren=conf_odds.get(rid2,{}).get('umaren',{})

        # 単勝（参考）
        winner=hns[wi[0]]
        for j,idx in enumerate(idxs):
            o=odds_te[idx]
            if o<=0: continue
            is_hit=int(hns[j]==winner)
            payout=hjc.get('win_hjc',{}).get(str(hns[j]),0) if is_hit else 0
            all_bets_win.append({'year':test_yr,'ev':float(p_raw[j]*o),'is_hit':is_hit,
                                 'payout':payout,'odds':o,'rid':rid2})

        # 馬連: 上位6頭の全15組
        rank_order=np.argsort(p_raw)[::-1]
        top6=rank_order[:min(6,len(rank_order))]
        for ci in combinations(range(len(top6)),2):
            i1,i2=top6[ci[0]],top6[ci[1]]
            key=tuple(sorted([i1,i2]))
            mdl_p=umaren_p.get(key,0)
            if mdl_p<=0: continue
            h1,h2=hns[key[0]],hns[key[1]]
            combo='-'.join(str(x) for x in sorted([h1,h2]))
            pool_odds=co_umaren.get(combo,0)
            if pool_odds<=0: continue
            ev=mdl_p*pool_odds
            fp1,fp2=fps.get(h1,99),fps.get(h2,99)
            is_hit=int(set([fp1,fp2])==set([1,2]))
            payout=hjc.get('umaren_hjc',{}).get(combo,0) if is_hit else 0
            # ランク情報
            r1=int(np.where(rank_order==key[0])[0][0])+1
            r2=int(np.where(rank_order==key[1])[0][0])+1
            rank_pair=f"{min(r1,r2)}-{max(r1,r2)}"
            all_bets.append({
                'year':test_yr,'month':month,'ev':float(ev),'is_hit':is_hit,
                'payout':payout,'pool_odds':pool_odds,'mdl_p':float(mdl_p),
                'rank_pair':rank_pair,'rid':rid2,'combo':combo,
                'r1':min(r1,r2),'r2':max(r1,r2)
            })

print(f"\n馬連ベット数: {len(all_bets):,}")
print(f"単勝ベット数: {len(all_bets_win):,}")

# =============================================
# 分析開始
# =============================================
print(f"\n{'='*90}")
print("v18: 馬連 深掘り分析（EV = モデル確率 × プール実オッズ）")
print(f"{'='*90}")

# --- 1. 全券種サマリー（EV閾値別 × 年別）---
print(f"\n--- 1. EV閾値別 × 年別 回収率 ---")
print(f"  {'EV>=':>6} {'ALL n':>7} {'ALL rec':>8} | {'2024 n':>7} {'2024':>7} | {'2025 n':>7} {'2025':>7} | {'2026 n':>7} {'2026':>7}")
print(f"  {'-'*85}")
for ev_th in [0.5, 0.8, 0.9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0]:
    sub=[d for d in all_bets if d['ev']>=ev_th]
    if not sub or len(sub)<10: continue
    n=len(sub); inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
    rec=pay/inv*100 if inv>0 else 0
    parts=[]
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: parts.append(f"{'':>7} {'':>7}"); continue
        yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
        parts.append(f"{len(ys):>7} {yp/yi*100:>6.1f}%")
    print(f"  {ev_th:>5.2f} {n:>7} {rec:>7.1f}% | {' | '.join(parts)}")

# --- 2. プールオッズ帯別 ---
print(f"\n--- 2. プールオッズ帯別（EV>=1.0）---")
print(f"  {'オッズ帯':>10} {'n':>6} {'的中':>5} {'的中率':>7} {'予測P':>7} {'比':>5} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"  {'-'*85}")
odds_bands = [(0,10),(10,20),(20,30),(30,50),(50,100),(100,200),(200,500),(500,9999)]
for lo,hi in odds_bands:
    sub=[d for d in all_bets if d['ev']>=1.0 and lo<=d['pool_odds']<hi]
    if len(sub)<5: continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
    avg_p=np.mean([d['mdl_p'] for d in sub]); ratio=hr/avg_p if avg_p>0 else 0
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
    parts=[]
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: parts.append(f"{'':>7}"); continue
        yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
        parts.append(f"{yp/yi*100:>6.1f}%")
    label=f"{lo}-{hi}x" if hi<9999 else f"{lo}x+"
    print(f"  {label:>10} {n:>6} {hits:>5} {hr:>6.2%} {avg_p:>6.4f} {ratio:>4.2f} {rec:>6.1f}% | {' '.join(parts)}")

# --- 3. ランクペア別 ---
print(f"\n--- 3. モデル順位ペア別（EV>=1.0）---")
print(f"  {'ペア':>5} {'n':>6} {'的中':>5} {'的中率':>7} {'平均EV':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"  {'-'*75}")
rank_pairs = ['1-2','1-3','1-4','1-5','1-6','2-3','2-4','2-5','2-6','3-4','3-5','3-6','4-5','4-6','5-6']
for rp in rank_pairs:
    sub=[d for d in all_bets if d['ev']>=1.0 and d['rank_pair']==rp]
    if len(sub)<5: continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
    avg_ev=np.mean([d['ev'] for d in sub])
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
    parts=[]
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: parts.append(f"{'':>7}"); continue
        yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
        parts.append(f"{yp/yi*100:>6.1f}%")
    print(f"  {rp:>5} {n:>6} {hits:>5} {hr:>6.2%} {avg_ev:>6.2f} {rec:>6.1f}% | {' '.join(parts)}")

# --- 4. 月別（全年）---
print(f"\n--- 4. 月別（EV>=1.0）---")
print(f"  {'月':>7} {'n':>6} {'的中':>5} {'的中率':>7} {'回収率':>7} {'累積回収率':>10}")
print(f"  {'-'*55}")
months=sorted(set(d['month'] for d in all_bets if d['ev']>=1.0 and d['month']))
cum_inv=0; cum_pay=0
for m in months:
    sub=[d for d in all_bets if d['ev']>=1.0 and d['month']==m]
    if not sub: continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
    cum_inv+=inv; cum_pay+=pay; cum_rec=cum_pay/cum_inv*100 if cum_inv>0 else 0
    print(f"  {m:>7} {n:>6} {hits:>5} {hr:>6.2%} {rec:>6.1f}% {cum_rec:>9.1f}%")

# --- 5. EV帯別キャリブレーション ---
print(f"\n--- 5. EV帯別キャリブレーション ---")
print(f"  {'EV帯':>10} {'n':>6} {'予測P':>7} {'実績P':>7} {'比':>5} {'回収率':>7} {'平均odds':>8}")
print(f"  {'-'*60}")
ev_bands = [(0.5,0.8),(0.8,1.0),(1.0,1.1),(1.1,1.2),(1.2,1.5),(1.5,3.0),(3.0,99)]
for lo,hi in ev_bands:
    sub=[d for d in all_bets if lo<=d['ev']<hi]
    if len(sub)<10: continue
    n=len(sub); avg_p=np.mean([d['mdl_p'] for d in sub]); avg_hit=np.mean([d['is_hit'] for d in sub])
    ratio=avg_hit/avg_p if avg_p>0 else 0
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
    avg_odds=np.mean([d['pool_odds'] for d in sub])
    label=f"{lo:.1f}-{hi:.1f}" if hi<99 else f"{lo:.1f}+"
    print(f"  {label:>10} {n:>6} {avg_p:>6.4f} {avg_hit:>6.4f} {ratio:>4.2f} {rec:>6.1f}% {avg_odds:>7.1f}")

# --- 6. 1年50%ルールチェック ---
print(f"\n--- 6. 1年50%ルールチェック ---")
for ev_th in [1.0, 1.1, 1.2]:
    sub=[d for d in all_bets if d['ev']>=ev_th]
    if not sub: continue
    total_n=len(sub); total_pay=sum(d['payout']*100 for d in sub if d['is_hit']); total_inv=total_n*100
    total_pnl=total_pay-total_inv
    print(f"\n  EV>={ev_th}:")
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: continue
        n=len(ys); inv=n*100; pay=sum(d['payout']*100 for d in ys if d['is_hit'])
        pnl=pay-inv; rec=pay/inv*100 if inv>0 else 0
        n_pct=n/total_n*100; pnl_pct=pnl/abs(total_pnl)*100 if total_pnl!=0 else 0
        flag="*** 50%超 ***" if abs(pnl_pct)>50 else ""
        print(f"    {yr}: n={n:,} ({n_pct:.0f}%) PnL={pnl:+,.0f}円 ({pnl_pct:+.0f}%) rec={rec:.1f}% {flag}")

# --- 7. ブートストラップCI ---
print(f"\n--- 7. ブートストラップCI（レースブロック、5000回）---")
for ev_th in [1.0, 1.1, 1.2]:
    sub=[d for d in all_bets if d['ev']>=ev_th]
    if len(sub)<50: continue
    by_race=defaultdict(list)
    for d in sub: by_race[d['rid']].append(d)
    race_ids=list(by_race.keys())
    if len(race_ids)<20: continue
    np.random.seed(42)
    boot_recs=[]
    for _ in range(5000):
        sample=np.random.choice(race_ids,size=len(race_ids),replace=True)
        s_inv=0; s_pay=0
        for rid in sample:
            for d in by_race[rid]:
                s_inv+=100
                if d['is_hit']: s_pay+=d['payout']*100
        if s_inv>0: boot_recs.append(s_pay/s_inv*100)
    boot_recs.sort()
    ci_lo=boot_recs[int(0.025*len(boot_recs))]
    ci_hi=boot_recs[int(0.975*len(boot_recs))]
    med=boot_recs[len(boot_recs)//2]
    print(f"  EV>={ev_th}: n={len(sub):,} ({len(race_ids)}R) median={med:.1f}% 95%CI=[{ci_lo:.1f}%, {ci_hi:.1f}%]")

# --- 8. 単勝との比較（参考）---
print(f"\n--- 8. 単勝との比較（参考、2-30x帯）---")
print(f"  {'券種':>6} {'EV>=':>5} {'n':>6} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"  {'-'*60}")
for ev_th in [1.0, 1.1, 1.2]:
    # 単勝
    sw=[d for d in all_bets_win if d['ev']>=ev_th and 2<=d['odds']<=30]
    if sw:
        n=len(sw); inv=n*100; pay=sum(d['payout']*100 for d in sw if d['is_hit']); rec=pay/inv*100
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sw if d['year']==yr]
            if not ys: parts.append(f"{'':>7}"); continue
            yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:>6.1f}%")
        print(f"  {'単勝':>6} {ev_th:>4.1f} {n:>6} {rec:>6.1f}% | {' '.join(parts)}")
    # 馬連
    su=[d for d in all_bets if d['ev']>=ev_th]
    if su:
        n=len(su); inv=n*100; pay=sum(d['payout']*100 for d in su if d['is_hit']); rec=pay/inv*100
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in su if d['year']==yr]
            if not ys: parts.append(f"{'':>7}"); continue
            yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:>6.1f}%")
        print(f"  {'馬連':>6} {ev_th:>4.1f} {n:>6} {rec:>6.1f}% | {' '.join(parts)}")

# --- 9. 上位N頭別比較 ---
print(f"\n--- 9. 上位N頭のEV>=1.2回収率比較 ---")
for top_n in [2, 3, 4, 5, 6]:
    sub=[d for d in all_bets if d['ev']>=1.2 and d['r1']<=top_n and d['r2']<=top_n]
    if len(sub)<5: continue
    n=len(sub); inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
    hits=sum(d['is_hit'] for d in sub)
    parts=[]
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: parts.append(f"{'':>7}"); continue
        yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
        parts.append(f"{yp/yi*100:>6.1f}%")
    print(f"  top{top_n}: n={n:,} hits={hits} rec={rec:.1f}% | {' '.join(parts)}")

print("\nDone!")
