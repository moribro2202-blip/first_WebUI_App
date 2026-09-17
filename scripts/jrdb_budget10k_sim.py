# -*- coding: utf-8 -*-
"""1R予算上限10,000円: 三連複+三連単の配分シミュレーション
先ほどのjrdb_optimal_bets.pyと同じWFパイプラインを使い、
予算配分パターンを網羅的にテスト
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
entry_cache = {}
for rid, _, _, _, _ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?', (rid,)).fetchall()
    if es:
        entry_cache[rid] = {e[0]: {'hid': e[1], 'jockey': e[2], 'trainer': e[3], 'idm': e[4], 'total': e[5], 'rider': e[6], 'run_style': e[7], 'weight': e[8]} for e in es}
result_cache = defaultdict(list)
result_full = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn': row[1], 'fp': row[2], 'hid': row[3]})
    result_full[row[0]][row[1]] = row[2]
race_cond = {r[0]: r[1] for r in db.execute('SELECT race_id,track_condition FROM races').fetchall()}
race_grade = {r[0]: r[1] for r in db.execute('SELECT race_id,grade FROM races').fetchall()}
race_horses = {}
for rid, _, _, _, _ in races_raw:
    hs = [e[0] for e in db.execute('SELECT horse_number FROM entries WHERE race_id=?', (rid,)).fetchall()]
    if hs: race_horses[rid] = sorted(hs)
ts_odds = {}
for mb in [0,1,2,3,5,10]:
    ts_odds[mb] = defaultdict(dict)
    for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=? AND odds>0',(mb,)).fetchall():
        ts_odds[mb][rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid, _, _, _, _ in races_raw:
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
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}
TAKEOUT = {'sanrenpuku':0.25,'sanrentan':0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']

def stern_harville_full(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3; S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float); trifecta={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                trio[tuple(sorted([i,j,k]))]+=pijk
                trifecta[(i,j,k)]=pijk
    return trio, trifecta

print("Building...", flush=True)
js={}; hh={}; ts_st={}
tr_ds={}; TRFNAMES=None; st_ds={}; STFNAMES=None

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
    o3=ts_odds[3].get(rid,{}); o5=ts_odds[5].get(rid,{})
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
    trio_mkt,trifecta_mkt=stern_harville_full(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    top1_idx=np.argmax(mp)
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
            f['last_fp']=runs[-1]['fp']; f['win_rate']=sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
        else: f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        f['win_odds_3min']=o3.get(h,0); feats_h[h]=f
    top8=[h for h,_ in sorted(odds_mkt.items(),key=lambda x:x[1])[:8]] if odds_mkt else hl[:8]
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    def make_trio_f(a,b,c):
        pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1,v2,v3=f1.get(k,0),f2.get(k,0),f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        ol=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=ol[0]/ol[-1] if len(ol)>=2 and ol[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in ol if o>0)
        return pf
    if len(top3_fps)>=3:
        wtr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in tr_ds: tr_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
        for a,b,c in combinations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c]))
            pf=make_trio_f(a,b,c)
            if TRFNAMES is None: TRFNAMES=sorted(pf.keys())
            tr_ds[year]['X'].append([pf.get(k,0) for k in TRFNAMES])
            tr_ds[year]['y'].append(1 if combo==wtr else 0)
            tr_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            tr_ds[year]['meta'].append((rid,combo)); tr_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrenpuku']))
            tr_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
    if len(top3_fps)>=3:
        wst=f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        if year not in st_ds: st_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
        for a,b,c in permutations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            if top1_idx not in (ai,bi,ci): continue
            sh_p=trifecta_mkt.get((ai,bi,ci),0)
            if sh_p<=0: continue
            combo=f'{a}-{b}-{c}'; pf=make_trio_f(a,b,c)
            pf['first_prob']=mp[ai]; pf['second_prob']=mp[bi]; pf['third_prob']=mp[ci]
            if STFNAMES is None: STFNAMES=sorted(pf.keys())
            st_ds[year]['X'].append([pf.get(k,0) for k in STFNAMES])
            st_ds[year]['y'].append(1 if combo==wst else 0)
            st_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            st_ds[year]['meta'].append((rid,combo)); st_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrentan']))
            st_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
    do_update()

for ds_name,ds_obj in [('trio',tr_ds),('sanrentan',st_ds)]:
    for y in sorted(ds_obj.keys()):
        d=ds_obj[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds']); d['pop']=np.array(d['pop'])

lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf_bets(ds,fnames,params,hjc_type):
    all_bets=[]
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in ds]; fit_yr=test_yr-1
        if not train_yrs or fit_yr not in ds or test_yr not in ds: continue
        X_tr=np.vstack([ds[y]['X'] for y in train_yrs]); y_tr=np.concatenate([ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([ds[y]['init'] for y in train_yrs])
        model=lgb.train(params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
        X_f=ds[fit_yr]['X']; y_f=ds[fit_yr]['y']; init_f=ds[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True); rd_f=defaultdict(list)
        for i,m in enumerate(ds[fit_yr]['meta']): rd_f[m[0]].append(i)
        def neg_ll(p):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max(); nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000}); b_use,tau_use=res.x
        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; odds_te=ds[test_yr]['odds']; pop_te=ds[test_yr]['pop']
        raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max(); probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; o=odds_te[idx]; ev=probs[j]*o; is_hit=y_te[idx]
                payout=hjc_all.get(rid2,{}).get(hjc_type,{}).get(str(combo) if isinstance(combo,int) else combo,0) if is_hit else 0
                all_bets.append({'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),'payout':payout,'odds':o,'pop':int(pop_te[idx]),'combo':combo})
    return all_bets

print("Running WF...", flush=True)
bets_trio = run_wf_bets(tr_ds,TRFNAMES,lgb_p,'sanrenpuku_hjc')
bets_st = run_wf_bets(st_ds,STFNAMES,lgb_p,'sanrentan_hjc')
print(f"  trio:{len(bets_trio):,}, st:{len(bets_st):,}")

trio_by_race = defaultdict(list)
st_by_race = defaultdict(list)
for b in bets_trio: trio_by_race[b['rid']].append(b)
for b in bets_st: st_by_race[b['rid']].append(b)
race_date_map = {r[0]:r[1] for r in races_raw}

def simulate(budget, tr_ev, st_ev, tr_max, st_max, pop_filter=1):
    """予算上限付きシミュレーション"""
    yr_invest=defaultdict(int); yr_return=defaultdict(float)
    total_invest=0; total_return=0.0; n_races=0; n_bets=0
    n_hit=0; n_hit_lose=0; race_details=[]

    all_rids = set(trio_by_race.keys()) | set(st_by_race.keys())
    for rid in all_rids:
        tr_cands=[b for b in trio_by_race.get(rid,[]) if b['ev']>=tr_ev and b['pop']<=pop_filter]
        tr_cands.sort(key=lambda x:-x['ev'])
        if tr_max>0: tr_cands=tr_cands[:tr_max]

        st_cands=[b for b in st_by_race.get(rid,[]) if b['ev']>=st_ev and b['pop']<=pop_filter]
        st_cands.sort(key=lambda x:-x['ev'])
        if st_max>0: st_cands=st_cands[:st_max]

        all_cands=tr_cands+st_cands
        if not all_cands: continue

        # 予算上限チェック: 全点100円で予算超過なら三連単を上から削る
        total_pts = len(all_cands)
        if total_pts * 100 > budget:
            # 三連複は維持、三連単をEV上位で予算内に
            remaining = budget // 100 - len(tr_cands)
            if remaining < 0:
                tr_cands = tr_cands[:budget // 100]
                st_cands = []
            else:
                st_cands = st_cands[:remaining]
            all_cands = tr_cands + st_cands

        if not all_cands: continue
        yr=all_cands[0]['year']
        race_invest=len(all_cands)*100
        race_return=sum(b['payout']*100 for b in all_cands if b['is_hit'])
        any_hit=any(b['is_hit'] for b in all_cands)
        if any_hit:
            n_hit+=1
            if race_return<race_invest: n_hit_lose+=1

        total_invest+=race_invest; total_return+=race_return
        yr_invest[yr]+=race_invest; yr_return[yr]+=race_return
        n_races+=1; n_bets+=len(all_cands)

        rd=race_date_map.get(rid,'?')
        race_details.append({'rid':rid,'date':rd,'year':yr,'n_trio':len(tr_cands),'n_st':len(st_cands),
                             'invest':race_invest,'return':race_return,'hit':any_hit})

    roi=total_return/total_invest*100 if total_invest>0 else 0
    yr_rois={yr:yr_return[yr]/yr_invest[yr]*100 if yr_invest[yr]>0 else 0 for yr in [2024,2025,2026]}
    avg_bets=n_bets/n_races if n_races>0 else 0
    hit_lose_pct=100*n_hit_lose/n_hit if n_hit>0 else 0
    avg_cost=total_invest/n_races if n_races>0 else 0
    return {'roi':roi,'profit':total_return-total_invest,'n_races':n_races,'n_bets':n_bets,
            'invest':total_invest,'avg_bets':avg_bets,'avg_cost':avg_cost,
            'yr_rois':yr_rois,'n_hit':n_hit,'hit_lose_pct':hit_lose_pct,
            'min_yr':min(yr_rois.values()) if yr_rois else 0,'details':race_details}

# === 網羅シミュレーション ===
print(f"\n{'='*140}")
print("1R予算上限10,000円: 三連複+三連単の最適配分")
print(f"{'='*140}")

configs = []
# パターン1: 三連単のみ
for st_ev in [1.0, 1.1, 1.2, 1.3, 1.5]:
    for st_max in [3, 5, 10, 15, 20, 30, 50, 100]:
        r = simulate(10000, 99, st_ev, 0, st_max)
        if r['n_bets'] < 100: continue
        configs.append(('三連単のみ', 0, st_ev, 0, st_max, r))

# パターン2: 三連複のみ
for tr_ev in [1.0, 1.1, 1.2, 1.3]:
    for tr_max in [3, 5, 10]:
        r = simulate(10000, tr_ev, 99, tr_max, 0)
        if r['n_bets'] < 100: continue
        configs.append(('三連複のみ', tr_ev, 0, tr_max, 0, r))

# パターン3: 三連複+三連単
for tr_ev in [1.0, 1.2, 1.3]:
    for st_ev in [1.0, 1.2, 1.3, 1.5]:
        for tr_max in [3, 5]:
            for st_max in [5, 10, 20, 30, 50, 95]:
                r = simulate(10000, tr_ev, st_ev, tr_max, st_max)
                if r['n_bets'] < 100: continue
                configs.append(('三連複+三連単', tr_ev, st_ev, tr_max, st_max, r))

# ROI順でソート
configs.sort(key=lambda x: -x[5]['roi'])

print(f"\n{'#':>3} {'type':>12} {'trEV':>5} {'stEV':>5} {'trMx':>4} {'stMx':>4} | {'R':>5} {'avg':>5} {'cost':>6} | {'ROI':>6} {'profit':>10} | {'2024':>7} {'2025':>7} {'2026':>7} | {'hit_lose':>8} {'min_yr':>7}")
print('-' * 130)
for i, (typ, tr_ev, st_ev, tmx, smx, r) in enumerate(configs[:40]):
    yr=r['yr_rois']
    tmx_s=str(tmx) if tmx>0 else '-'
    smx_s=str(smx) if smx>0 else '-'
    tr_ev_s=f'{tr_ev:.1f}' if tr_ev<90 else '  -'
    st_ev_s=f'{st_ev:.1f}' if st_ev<90 else '  -'
    print(f"{i+1:>3} {typ:>12} {tr_ev_s:>5} {st_ev_s:>5} {tmx_s:>4} {smx_s:>4} | {r['n_races']:>5} {r['avg_bets']:>5.1f} {r['avg_cost']:>5.0f}円 | {r['roi']:>5.1f}% {r['profit']:>+9,.0f} | {yr[2024]:>6.1f}% {yr[2025]:>6.1f}% {yr[2026]:>6.1f}% | {r['hit_lose_pct']:>7.1f}% {r['min_yr']:>6.1f}%")

# === 安定性フィルタ（3年とも100%超 AND 的中負け<=15%） ===
print(f"\n{'='*140}")
print("安定設定（3年とも100%超 AND 的中負け率<=15%）")
print(f"{'='*140}")
stable = [x for x in configs if x[5]['min_yr']>100 and x[5]['hit_lose_pct']<=15 and x[5]['n_bets']>=300]
stable.sort(key=lambda x: -x[5]['profit'])

print(f"{'#':>3} {'type':>12} {'trEV':>5} {'stEV':>5} {'trMx':>4} {'stMx':>4} | {'R':>5} {'avg':>5} {'cost':>6} | {'ROI':>6} {'profit':>10} | {'2024':>7} {'2025':>7} {'2026':>7} | {'hit_lose':>8}")
print('-' * 130)
for i, (typ, tr_ev, st_ev, tmx, smx, r) in enumerate(stable[:25]):
    yr=r['yr_rois']
    tmx_s=str(tmx) if tmx>0 else '-'
    smx_s=str(smx) if smx>0 else '-'
    tr_ev_s=f'{tr_ev:.1f}' if tr_ev<90 else '  -'
    st_ev_s=f'{st_ev:.1f}' if st_ev<90 else '  -'
    print(f"{i+1:>3} {typ:>12} {tr_ev_s:>5} {st_ev_s:>5} {tmx_s:>4} {smx_s:>4} | {r['n_races']:>5} {r['avg_bets']:>5.1f} {r['avg_cost']:>5.0f}円 | {r['roi']:>5.1f}% {r['profit']:>+9,.0f} | {yr[2024]:>6.1f}% {yr[2025]:>6.1f}% {yr[2026]:>6.1f}% | {r['hit_lose_pct']:>7.1f}%")

# === ベスト設定の月別詳細 ===
if stable:
    best = stable[0]
    typ, tr_ev, st_ev, tmx, smx, r = best
    print(f"\n{'='*140}")
    print(f"ベスト設定の月別損益: {typ} trEV>={tr_ev} stEV>={st_ev} trMax={tmx} stMax={smx}")
    print(f"{'='*140}")

    monthly = defaultdict(lambda: {'invest':0,'return':0.0,'races':0,'hits':0})
    for d in r['details']:
        month = d['date'][:7]
        monthly[month]['invest'] += d['invest']
        monthly[month]['return'] += d['return']
        monthly[month]['races'] += 1
        if d['hit']: monthly[month]['hits'] += 1

    print(f"{'月':>8} | {'R':>4} | {'的中':>3} | {'投資':>10} | {'払戻':>10} | {'損益':>10} | {'ROI':>6} | {'累積損益':>10}")
    print('-'*85)
    cum=0
    black_months=0
    for m in sorted(monthly.keys()):
        v=monthly[m]; roi=v['return']/v['invest']*100 if v['invest']>0 else 0
        pnl=v['return']-v['invest']; cum+=pnl
        if pnl>0: black_months+=1
        print(f"{m:>8} | {v['races']:>4} | {v['hits']:>3} | {v['invest']:>9,}円 | {v['return']:>9,.0f}円 | {pnl:>+9,.0f}円 | {roi:>5.1f}% | {cum:>+9,.0f}円")
    total_m=len(monthly)
    print(f"\n  黒字月: {black_months}/{total_m} ({100*black_months/total_m:.0f}%)")
    print(f"  累積損益: {cum:>+,.0f}円")

print("\nDone!")
