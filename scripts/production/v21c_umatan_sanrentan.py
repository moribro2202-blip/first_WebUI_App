# -*- coding: utf-8 -*-
"""v21c: 馬単・三連単 SH基準（リークなし）
単勝3分前オッズからSH順列確率を算出
推定オッズ = 1/SH確率 × (1-控除率)
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
TAKEOUT = {'umatan': 0.225, 'sanrentan': 0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_ordered(p):
    """SH順列確率（馬単・三連単用）"""
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    umatan={}; sanrentan={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umatan[(i,j)]=pij  # i=1着, j=2着（順序あり）
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                sanrentan[(i,j,k)]=pij*(p3[k]/d3)  # i=1着,j=2着,k=3着
    return umatan, sanrentan

# データセット構築
print("Building datasets...", flush=True)
js={}; hh={}; ts_st={}
ds = {'umatan':{}, 'sanrentan':{}}
FNAMES = {'umatan': None, 'sanrentan': None}

for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
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
    fps=result_full.get(rid,{}); hjc=hjc_all.get(rid,{}); month=rd[:7]

    umatan_mkt, sanrentan_mkt = sh_ordered(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    top6=[h for h,_ in sorted_h[:6]] if sorted_h else hl[:6]

    # 馬ごと特徴量
    feats_h={}
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

    # 1着-2着（馬単）
    top2_fps=sorted([r for r in rl if r['fp'] in (1,2)],key=lambda x:x['fp'])
    if len(top2_fps)>=2:
        winner_ut=f"{top2_fps[0]['hn']}-{top2_fps[1]['hn']}"
        if year not in ds['umatan']:
            ds['umatan'][year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'month':[]}
        # 上位6頭のP(6,2)=30通り
        for h1 in top6:
            for h2 in top6:
                if h1==h2: continue
                i1=hl.index(h1); i2=hl.index(h2)
                sh_p=umatan_mkt.get((i1,i2),0)
                if sh_p<=0: continue
                combo=f"{h1}-{h2}"
                est_odds=(1/sh_p)*(1-TAKEOUT['umatan'])
                f1=feats_h[h1]; f2=feats_h[h2]
                pf={}
                for k in FEAT_KEYS:
                    pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0)
                    pf[f'{k}_diff']=f1.get(k,0)-f2.get(k,0)  # 順序あり: 1着候補-2着候補
                pf['first_odds']=f1.get('win_odds_3min',0)
                pf['second_odds']=f2.get('win_odds_3min',0)
                if FNAMES['umatan'] is None: FNAMES['umatan']=sorted(pf.keys())
                init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
                is_hit=1 if combo==winner_ut else 0
                payout=hjc.get('umatan_hjc',{}).get(combo,0) if is_hit else 0
                pop=min(rank_map.get(h1,99),rank_map.get(h2,99))
                ds['umatan'][year]['X'].append([pf.get(k,0) for k in FNAMES['umatan']])
                ds['umatan'][year]['y'].append(is_hit)
                ds['umatan'][year]['init'].append(init)
                ds['umatan'][year]['meta'].append((rid,combo))
                ds['umatan'][year]['odds'].append(est_odds)
                ds['umatan'][year]['pop'].append(pop)
                ds['umatan'][year]['month'].append(month)

    # 1着-2着-3着（三連単）
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    if len(top3_fps)>=3:
        winner_st=f"{top3_fps[0]['hn']}-{top3_fps[1]['hn']}-{top3_fps[2]['hn']}"
        if year not in ds['sanrentan']:
            ds['sanrentan'][year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'month':[]}
        # 上位5頭のP(5,3)=60通り（メモリ節約）
        top5=[h for h,_ in sorted_h[:5]] if sorted_h else hl[:5]
        for perm in permutations(top5, 3):
            h1,h2,h3=perm
            i1=hl.index(h1); i2=hl.index(h2); i3=hl.index(h3)
            sh_p=sanrentan_mkt.get((i1,i2,i3),0)
            if sh_p<=0: continue
            combo=f"{h1}-{h2}-{h3}"
            est_odds=(1/sh_p)*(1-TAKEOUT['sanrentan'])
            f1=feats_h[h1]; f2=feats_h[h2]; f3=feats_h[h3]
            pf={}
            for k in FEAT_KEYS:
                pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0)+f3.get(k,0)
                pf[f'{k}_spread']=max(f1.get(k,0),f2.get(k,0),f3.get(k,0))-min(f1.get(k,0),f2.get(k,0),f3.get(k,0))
            pf['first_odds']=f1.get('win_odds_3min',0)
            pf['second_odds']=f2.get('win_odds_3min',0)
            pf['third_odds']=f3.get('win_odds_3min',0)
            if FNAMES['sanrentan'] is None: FNAMES['sanrentan']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_st else 0
            payout=hjc.get('sanrentan_hjc',{}).get(combo,0) if is_hit else 0
            pop=min(rank_map.get(h1,99),rank_map.get(h2,99),rank_map.get(h3,99))
            ds['sanrentan'][year]['X'].append([pf.get(k,0) for k in FNAMES['sanrentan']])
            ds['sanrentan'][year]['y'].append(is_hit)
            ds['sanrentan'][year]['init'].append(init)
            ds['sanrentan'][year]['meta'].append((rid,combo))
            ds['sanrentan'][year]['odds'].append(est_odds)
            ds['sanrentan'][year]['pop'].append(pop)
            ds['sanrentan'][year]['month'].append(month)
    do_update()

for bt in ds:
    for y in sorted(ds[bt].keys()):
        d=ds[bt][y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        d['pop']=np.array(d['pop'])
    sizes=', '.join(str(y)+':'+str(len(ds[bt][y]['X'])) for y in sorted(ds[bt].keys()))
    print(f"  {bt}: {sizes}")

# WF
lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(bt_ds, fnames, label, hjc_type):
    print(f"\n--- {label} ---")
    all_bets=[]
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in bt_ds]; fit_yr=test_yr-1
        if not train_yrs or fit_yr not in bt_ds or test_yr not in bt_ds: continue
        X_tr=np.vstack([bt_ds[y]['X'] for y in train_yrs])
        y_tr=np.concatenate([bt_ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([bt_ds[y]['init'] for y in train_yrs])
        model=lgb.train(lgb_params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
        X_f=bt_ds[fit_yr]['X']; y_f=bt_ds[fit_yr]['y']; init_f=bt_ds[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,combo) in enumerate(bt_ds[fit_yr]['meta']): rd_f[rid].append(i)
        def neg_ll(p):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        b_use,tau_use=res.x; print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")
        X_te=bt_ds[test_yr]['X']; y_te=bt_ds[test_yr]['y']; init_te=bt_ds[test_yr]['init']
        meta_te=bt_ds[test_yr]['meta']; odds_te=bt_ds[test_yr]['odds']
        pop_te=bt_ds[test_yr]['pop']; month_te=bt_ds[test_yr]['month']
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,combo) in enumerate(meta_te): rd_te[rid].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                ev=probs[j]*odds_te[idx]
                is_hit=y_te[idx]
                payout=hjc_all.get(rid2,{}).get(hjc_type,{}).get(meta_te[idx][1],0) if is_hit else 0
                all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'odds':odds_te[idx],
                                 'pop':int(pop_te[idx]),'rid':rid2,'month':month_te[idx]})
    return all_bets

print("\nWF...", flush=True)
bets_ut = run_wf(ds['umatan'], FNAMES['umatan'], '馬単(SH基準)', 'umatan_hjc')
bets_st = run_wf(ds['sanrentan'], FNAMES['sanrentan'], '三連単(SH基準)', 'sanrentan_hjc')

# 結果
BET=100
print(f"\n{'='*90}")
print("v21c: 馬単・三連単 SH基準（リークなし）")
print(f"{'='*90}")

for bt_label, data in [('馬単', bets_ut), ('三連単', bets_st)]:
    print(f"\n  {bt_label}:")
    print(f"  {'フィルタ':>14} {'EV>=':>5} {'n':>7} {'的中':>5} {'的中率':>7} {'回収率':>7} {'R数':>6} {'点/R':>5} | {'2024':>7} {'2025':>7} {'2026':>7}")
    print(f"  {'-'*90}")
    for pop_label, pop_max in [('1番人気含む',1),('1-3番人気含む',3),('全組合せ',99)]:
        for ev_th in [1.0, 1.2, 1.5]:
            sub=[d for d in data if d['ev']>=ev_th and d['pop']<=pop_max]
            if not sub or len(sub)<10: continue
            n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
            inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
            n_races=len(set(d['rid'] for d in sub)); pts_r=n/max(n_races,1)
            parts=[]
            for yr in [2024,2025,2026]:
                ys=[d for d in sub if d['year']==yr]
                if not ys: parts.append(''); continue
                yi=len(ys)*BET; yp=sum(d['payout']*BET for d in ys if d['is_hit'])
                parts.append(f"{yp/yi*100:.1f}%")
            print(f"  {pop_label:>14} {ev_th:>4.1f} {n:>7} {hits:>5} {hr:>6.2%} {rec:>6.1f}% {n_races:>6} {pts_r:>4.1f} | {' '.join(parts)}")

# 全券種比較（1番人気含む EV>=1.2、1R=1000円）
print(f"\n{'='*90}")
print("全券種比較（1番人気含む × EV>=1.2、1R=1000円投資）")
print(f"{'='*90}")
print(f"{'券種':>12} {'回収率':>7} {'R/年':>6} {'点/R':>5} {'年間投資':>10} {'年間PnL':>10}")
print(f"{'-'*60}")
# v21の結果も含める
all_results = [
    ('単勝', 112.8, 1093, 1.1),
    ('馬連', 115.8, 1269, 1.8),
    ('三連複', 130.9, 1880, 5.3),
]
for bt_label, data in [('馬単', bets_ut), ('三連単', bets_st)]:
    sub=[d for d in data if d['ev']>=1.2 and d['pop']<=1]
    if not sub or len(sub)<10: continue
    n=len(sub); inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
    n_races=len(set(d['rid'] for d in sub)); pts_r=n/max(n_races,1)
    r_per_year=n_races/3
    all_results.append((bt_label, rec, r_per_year, pts_r))

for name, rec, r_yr, pts in sorted(all_results, key=lambda x:-x[1]*(x[2]*1000*(x[1]/100-1) if x[1]>100 else 0)):
    annual_inv = r_yr * 1000
    annual_pnl = annual_inv * (rec/100 - 1)
    print(f"{name:>12} {rec:>6.1f}% {r_yr:>5.0f} {pts:>4.1f} {annual_inv:>9,.0f}円 {annual_pnl:>+9,.0f}円")

print("\nDone!")
