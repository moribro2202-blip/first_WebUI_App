# -*- coding: utf-8 -*-
"""v18b: ワイド・三連複・三連単の深掘り分析
EV = モデル確率 × プール実オッズ（confirmed_odds）
払戻 = HJC確定オッズ
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

# confirmed_odds全券種
print("  Loading confirmed_odds...", flush=True)
conf_odds = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM confirmed_odds WHERE odds>0 AND bet_type IN ('wide','umaren','sanrenpuku','sanrentan')").fetchall():
    conf_odds[row[0]][row[1]][row[2]] = row[3]
print(f"  confirmed_odds loaded", flush=True)

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

def stern_harville_full(p):
    """全券種の確率を一括計算（ワイド・馬連・三連複・三連単）"""
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    wide=defaultdict(float); umaren=defaultdict(float)
    trio=defaultdict(float); trifecta=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+=pij
            trifecta_ij = pij  # P(i=1st, j=2nd)
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                for a,b in combinations(sorted([i,j,k]),2): wide[(a,b)]+=pijk
                trio[tuple(sorted([i,j,k]))]+=pijk
                # 三連単: (i->1st, j->2nd, k->3rd) の順列確率
                trifecta[(i,j,k)]+=pijk
    return wide, umaren, trio, trifecta

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
bets = {'wide':[], 'trio':[], 'trifecta':[], 'win':[]}

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

    n_proc=0
    for rid2,idxs in race_data.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
        p_raw=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[i][1] for i in idxs]
        fps=result_full.get(rid2,{})
        hjc=hjc_all.get(rid2,{})
        co=conf_odds.get(rid2,{})

        wide_p, umaren_p, trio_p, trifecta_p = stern_harville_full(p_raw)
        rank_order=np.argsort(p_raw)[::-1]
        top6=rank_order[:min(6,len(rank_order))]

        # 単勝（参考）
        winner=hns[wi[0]]
        for j,idx in enumerate(idxs):
            o=odds_te[idx]
            if o<=0: continue
            is_hit=int(hns[j]==winner)
            payout=hjc.get('win_hjc',{}).get(str(hns[j]),0) if is_hit else 0
            bets['win'].append({'year':test_yr,'ev':float(p_raw[j]*o),'is_hit':is_hit,
                                'payout':payout,'odds':o,'rid':rid2})

        # ワイド: 上位6頭の全C(6,2)=15組
        co_w=co.get('wide',{})
        for ci in combinations(range(len(top6)),2):
            i1,i2=top6[ci[0]],top6[ci[1]]
            key=tuple(sorted([i1,i2]))
            mdl_p=wide_p.get(key,0)
            if mdl_p<=0: continue
            h1,h2=hns[key[0]],hns[key[1]]
            combo='-'.join(str(x) for x in sorted([h1,h2]))
            pool_odds=co_w.get(combo,0)
            if pool_odds<=0: continue
            ev=mdl_p*pool_odds
            fp1,fp2=fps.get(h1,99),fps.get(h2,99)
            is_hit=int(fp1<=3 and fp2<=3)
            payout=hjc.get('wide_hjc',{}).get(combo,0) if is_hit else 0
            bets['wide'].append({'year':test_yr,'ev':float(ev),'is_hit':is_hit,
                                 'payout':payout,'pool_odds':pool_odds,'mdl_p':float(mdl_p),'rid':rid2})

        # 三連複: 上位6頭のC(6,3)=20組
        co_t=co.get('sanrenpuku',{})
        for ci in combinations(range(len(top6)),3):
            i1,i2,i3=top6[ci[0]],top6[ci[1]],top6[ci[2]]
            key=tuple(sorted([i1,i2,i3]))
            mdl_p=trio_p.get(key,0)
            if mdl_p<=0: continue
            h1,h2,h3=hns[key[0]],hns[key[1]],hns[key[2]]
            combo='-'.join(str(x) for x in sorted([h1,h2,h3]))
            pool_odds=co_t.get(combo,0)
            if pool_odds<=0: continue
            ev=mdl_p*pool_odds
            fps3=set([fps.get(h1,99),fps.get(h2,99),fps.get(h3,99)])
            is_hit=int(fps3==set([1,2,3]))
            payout=hjc.get('sanrenpuku_hjc',{}).get(combo,0) if is_hit else 0
            bets['trio'].append({'year':test_yr,'ev':float(ev),'is_hit':is_hit,
                                 'payout':payout,'pool_odds':pool_odds,'mdl_p':float(mdl_p),'rid':rid2})

        # 三連単: 上位4頭のP(4,3)=24通り
        co_s=co.get('sanrentan',{})
        top4=rank_order[:min(4,len(rank_order))]
        for perm in permutations(range(len(top4)),3):
            i1,i2,i3=top4[perm[0]],top4[perm[1]],top4[perm[2]]
            mdl_p=trifecta_p.get((i1,i2,i3),0)
            if mdl_p<=0: continue
            h1,h2,h3=hns[i1],hns[i2],hns[i3]
            combo=f"{h1}-{h2}-{h3}"
            pool_odds=co_s.get(combo,0)
            if pool_odds<=0: continue
            ev=mdl_p*pool_odds
            fp1,fp2,fp3=fps.get(h1,99),fps.get(h2,99),fps.get(h3,99)
            is_hit=int(fp1==1 and fp2==2 and fp3==3)
            payout=hjc.get('sanrentan_hjc',{}).get(combo,0) if is_hit else 0
            bets['trifecta'].append({'year':test_yr,'ev':float(ev),'is_hit':is_hit,
                                     'payout':payout,'pool_odds':pool_odds,'mdl_p':float(mdl_p),'rid':rid2})

        n_proc+=1
        if n_proc%1000==0: print(f"    {test_yr}: {n_proc}R", flush=True)

for bt in bets:
    print(f"  {bt}: {len(bets[bt]):,}")

# =============================================
def analyze(data, label):
    print(f"\n{'='*90}")
    print(f"■ {label}")
    print(f"{'='*90}")

    if not data:
        print("  データなし")
        return

    # 1. EV閾値別×年別
    print(f"\n  --- EV閾値別 × 年別 ---")
    print(f"  {'EV>=':>6} {'ALL n':>7} {'ALL rec':>8} | {'2024 n':>7} {'2024':>7} | {'2025 n':>7} {'2025':>7} | {'2026 n':>7} {'2026':>7}")
    print(f"  {'-'*85}")
    for ev_th in [0.5, 0.8, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0, 3.0]:
        sub=[d for d in data if d['ev']>=ev_th]
        if not sub or len(sub)<10: continue
        n=len(sub); inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
        rec=pay/inv*100 if inv>0 else 0
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: parts.append(f"{'':>7} {'':>7}"); continue
            yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f"{len(ys):>7} {yp/yi*100:>6.1f}%")
        print(f"  {ev_th:>5.1f} {n:>7} {rec:>7.1f}% | {' | '.join(parts)}")

    # 2. プールオッズ帯別（EV>=1.0）
    print(f"\n  --- プールオッズ帯別（EV>=1.0）---")
    print(f"  {'オッズ帯':>12} {'n':>6} {'的中':>5} {'的中率':>7} {'予測P':>7} {'比':>5} {'回収率':>7}")
    print(f"  {'-'*60}")
    odds_bands = [(0,10),(10,20),(20,50),(50,100),(100,200),(200,500),(500,1000),(1000,5000),(5000,99999)]
    for lo,hi in odds_bands:
        sub=[d for d in data if d['ev']>=1.0 and lo<=d['pool_odds']<hi]
        if len(sub)<5: continue
        n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
        avg_p=np.mean([d['mdl_p'] for d in sub]); ratio=hr/avg_p if avg_p>0 else 0
        inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
        label2=f"{lo}-{hi}x" if hi<99999 else f"{lo}x+"
        print(f"  {label2:>12} {n:>6} {hits:>5} {hr:>6.2%} {avg_p:>6.4f} {ratio:>4.2f} {rec:>6.1f}%")

    # 3. EV帯別キャリブレーション
    print(f"\n  --- EV帯別キャリブレーション ---")
    print(f"  {'EV帯':>10} {'n':>7} {'予測P':>8} {'実績P':>8} {'比':>5} {'回収率':>7} {'平均odds':>8}")
    print(f"  {'-'*65}")
    ev_bands = [(0.5,0.8),(0.8,1.0),(1.0,1.2),(1.2,1.5),(1.5,2.0),(2.0,3.0),(3.0,5.0),(5.0,99)]
    for lo,hi in ev_bands:
        sub=[d for d in data if lo<=d['ev']<hi]
        if len(sub)<10: continue
        n=len(sub); avg_p=np.mean([d['mdl_p'] for d in sub]); avg_hit=np.mean([d['is_hit'] for d in sub])
        ratio=avg_hit/avg_p if avg_p>0 else 0
        inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
        avg_odds=np.mean([d['pool_odds'] for d in sub])
        label2=f"{lo:.1f}-{hi:.1f}" if hi<99 else f"{lo:.1f}+"
        print(f"  {label2:>10} {n:>7} {avg_p:>7.5f} {avg_hit:>7.5f} {ratio:>4.2f} {rec:>6.1f}% {avg_odds:>7.1f}")

    # 4. 1年50%ルール
    print(f"\n  --- 1年50%ルール ---")
    for ev_th in [1.0, 1.2]:
        sub=[d for d in data if d['ev']>=ev_th]
        if not sub: continue
        total_n=len(sub); total_inv=total_n*100
        total_pay=sum(d['payout']*100 for d in sub if d['is_hit']); total_pnl=total_pay-total_inv
        print(f"  EV>={ev_th}:  total PnL={total_pnl:+,.0f}円")
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: continue
            n=len(ys); inv=n*100; pay=sum(d['payout']*100 for d in ys if d['is_hit'])
            pnl=pay-inv; rec=pay/inv*100 if inv>0 else 0
            pnl_pct=pnl/abs(total_pnl)*100 if total_pnl!=0 else 0
            flag="*** 50%超 ***" if abs(pnl_pct)>50 else ""
            print(f"    {yr}: n={n:,} PnL={pnl:+,.0f}円 ({pnl_pct:+.0f}%) rec={rec:.1f}% {flag}")

    # 5. ブートストラップCI
    print(f"\n  --- ブートストラップCI（5000回）---")
    for ev_th in [1.0, 1.2, 1.5]:
        sub=[d for d in data if d['ev']>=ev_th]
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
        print(f"  EV>={ev_th}: n={len(sub):,} ({len(race_ids)}R) med={med:.1f}% 95%CI=[{ci_lo:.1f}%, {ci_hi:.1f}%]")

# =============================================
# 実行
# =============================================
analyze(bets['wide'], "ワイド（上位6頭15組、EV=modelP×プール実オッズ）")
analyze(bets['trio'], "三連複（上位6頭20組、EV=modelP×プール実オッズ）")
analyze(bets['trifecta'], "三連単（上位4頭24通り、EV=modelP×プール実オッズ）")

# 全券種サマリー
print(f"\n{'='*90}")
print("全券種サマリー（EV>=1.0 / EV>=1.2 / EV>=1.5）")
print(f"{'='*90}")
print(f"  {'券種':>8} {'EV>=':>5} {'n':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"  {'-'*65}")
for bt,label in [('win','単勝(2-30x)'),('wide','ワイド'),('trio','三連複'),('trifecta','三連単')]:
    for ev_th in [1.0, 1.2, 1.5]:
        if bt=='win':
            sub=[d for d in bets[bt] if d['ev']>=ev_th and 2<=d['odds']<=30]
        else:
            sub=[d for d in bets[bt] if d['ev']>=ev_th]
        if not sub or len(sub)<5: continue
        n=len(sub); inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: parts.append(f"{'':>7}"); continue
            yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:>6.1f}%")
        print(f"  {label:>8} {ev_th:>4.1f} {n:>7} {rec:>6.1f}% | {' '.join(parts)}")

print("\nDone!")
