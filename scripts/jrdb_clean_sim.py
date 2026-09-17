# -*- coding: utf-8 -*-
"""クリーンシミュレーション: 三連複モデルベース + 券種選択
三連単モデルのバグ（順序対称特徴量で170%）を排除し、
検証済みの三連複モデル（118.6%）のみをベースに構築。

戦略:
  1. 三連複モデルでEV>=閾値のトリオを選択
  2. 各トリオについて、三連複 vs 三連単ボックスを比較:
     - 三連複: 1点100円、払戻=三連複HJC×100
     - 三連単box: 6点600円、払戻=三連単HJC×100
     - ROI比較で有利な方を選択
  3. 合理的点数: 予算内でEV上位から
  4. 単勝も併用: 三連複モデルの対象外レースで単勝

全て100円単位。HJC確定オッズで払戻計算。
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
ts_odds = {}
for mb in [0,1,2,3,5,10]:
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
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
hjc_win = defaultdict(dict)
for row in db.execute("SELECT race_id,combination,odds FROM odds WHERE bet_type='win_hjc' AND odds>0").fetchall():
    try: hjc_win[row[0]][int(row[1])] = row[2]
    except: pass
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
TAKEOUT_TRIO = 0.25
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_trio(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3; S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2); d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                trio[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    return trio

# === Build trio dataset (same as v21/v22 fixed) ===
print("Building trio dataset...", flush=True)
js={}; hh={}; ts_st={}
tr_ds={}; TRFNAMES=None
# Also build single-win dataset for comparison
win_ds={}; WFNAMES=None

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
    trio_mkt=sh_trio(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1]); rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    feats_h={}
    for i,h in enumerate(hl):
        ent=entries.get(h,{}); f={}
        f['idm_c']=(ent.get('idm') or 50)-avg_idm; f['rider_c']=(ent.get('rider') or 0)-avg_rider
        f['total_index']=ent.get('total') or 0
        oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
        f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
        f['cyb_c']=cyb_cache.get((rid,h),0)-avg_cyb
        jn=ent.get('jockey',''); tn=ent.get('trainer','')
        jst=js.get(jn,{}); f['jockey_t3rate']=jst.get('t3',0)/jst['r'] if jst.get('r',0)>=30 else -1
        tst=ts_st.get(tn,{}); f['trainer_t3rate']=tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
        runs=hh.get(ent.get('hid',''),[])
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
    def make_trio(a,b,c):
        pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1,v2,v3=f1.get(k,0),f2.get(k,0),f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        ol=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=ol[0]/ol[-1] if len(ol)>=2 and ol[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in ol if o>0)
        return pf

    # 三連複
    if len(top3_fps)>=3:
        wtr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in tr_ds: tr_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'sh_prob':[]}
        for a,b,c in combinations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c])); pf=make_trio(a,b,c)
            if TRFNAMES is None: TRFNAMES=sorted(pf.keys())
            tr_ds[year]['X'].append([pf.get(k,0) for k in TRFNAMES])
            tr_ds[year]['y'].append(1 if combo==wtr else 0)
            tr_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            tr_ds[year]['meta'].append((rid,combo))
            tr_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT_TRIO))
            tr_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            tr_ds[year]['sh_prob'].append(float(sh_p))

    # 単勝
    if year not in win_ds: win_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    wfn = sorted(FEAT_KEYS)
    if WFNAMES is None: WFNAMES = wfn
    for i,h in enumerate(hl):
        win_ds[year]['X'].append([feats_h[h].get(k,0) for k in WFNAMES])
        win_ds[year]['y'].append(1 if h==winners[0] else 0)
        win_ds[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        win_ds[year]['meta'].append((rid,h)); win_ds[year]['odds'].append(o3.get(h,0))
    do_update()

for ds in [tr_ds, win_ds]:
    for y in sorted(ds.keys()):
        d=ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        if 'sh_prob' in d: d['sh_prob']=np.array(d['sh_prob'])
        if 'pop' in d: d['pop']=np.array(d['pop'])

for ds_name, ds_obj in [('trio',tr_ds),('win',win_ds)]:
    sizes=', '.join(f'{y}:{len(ds_obj[y]["X"])}' for y in sorted(ds_obj.keys()))
    print(f"  {ds_name}: {sizes}")

lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(ds, fnames, params, hjc_type):
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
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000}); b_use,tau_use=res.x
        print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")

        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; odds_te=ds[test_yr]['odds']
        sh_te=ds[test_yr].get('sh_prob', np.zeros(len(y_te)))
        pop_te=ds[test_yr].get('pop', np.zeros(len(y_te)))
        raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            pr=np.exp(s)/np.exp(s).sum()
            sh_sum=sh_te[idxs].sum() if sh_te[idxs].sum()>0 else 1.0
            pa=pr*sh_sum  # fix: absolute prob
            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; est_o=odds_te[idx]
                ev=pa[j]*est_o; is_hit=y_te[idx]
                payout_hjc=hjc_all.get(rid2,{}).get(hjc_type,{}).get(str(combo) if isinstance(combo,int) else combo,0) if is_hit else 0
                # Also get sanrentan HJC for same trio (if trio type)
                st_payout=0
                if is_hit and hjc_type=='sanrenpuku_hjc':
                    fps=result_full.get(rid2,{})
                    horses_in_combo=combo.split('-')
                    top3=sorted([(int(h),fps.get(int(h),99)) for h in horses_in_combo],key=lambda x:x[1])
                    st_combo=f'{top3[0][0]}-{top3[1][0]}-{top3[2][0]}'
                    st_payout=hjc_all.get(rid2,{}).get('sanrentan_hjc',{}).get(st_combo,0)
                pop_val=int(pop_te[idx]) if len(pop_te)>idx else 0
                all_bets.append({'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout_trio':payout_hjc,'payout_st':st_payout,
                                 'est_odds':float(est_o),'model_prob':float(pa[j]),
                                 'pop':pop_val,'combo':combo})
    return all_bets

print("\nRunning WF...", flush=True)
print("  Trio:")
bets_trio = run_wf(tr_ds, TRFNAMES, lgb_p, 'sanrenpuku_hjc')
print("  Win:")
bets_win = run_wf(win_ds, WFNAMES, lgb_w, 'win_hjc')

# === 戦略シミュレーション ===
print(f"\n{'='*100}")
print("クリーンシミュレーション: 100円単位、合理的点数")
print(f"{'='*100}")

race_date_map = {r[0]:r[1] for r in races_raw}

def sim_strategy(label, trio_bets, win_bets, ev_th_trio, ev_th_win, pop_max,
                 max_trio_pts, budget, buy_as):
    """
    buy_as: 'trio'=三連複1点, 'st_box'=三連単ボックス6点, 'best'=比較して有利な方
    """
    # レース別に整理
    trio_by_race = defaultdict(list)
    win_by_race = defaultdict(list)
    for b in trio_bets:
        if b['ev']>=ev_th_trio and b['pop']<=pop_max:
            trio_by_race[b['rid']].append(b)
    for b in win_bets:
        if b['ev']>=ev_th_win and 2<=b['est_odds']<=40:
            win_by_race[b['rid']].append(b)

    yr_invest=defaultdict(int); yr_return=defaultdict(float)
    total_invest=0; total_return=0.0; n_races=0; n_bets=0
    n_hit=0; n_hit_lose=0
    bet_type_counts = defaultdict(int)

    all_rids = set(trio_by_race.keys()) | set(win_by_race.keys())
    for rid in all_rids:
        tr = sorted(trio_by_race.get(rid,[]), key=lambda x:-x['ev'])[:max_trio_pts]
        wn = sorted(win_by_race.get(rid,[]), key=lambda x:-x['ev'])

        if not tr and not wn: continue
        yr = (tr[0] if tr else wn[0])['year']

        race_invest = 0
        race_return = 0.0

        # 三連複/三連単ボックスの購入
        for b in tr:
            if buy_as == 'trio':
                cost = 100
                ret = b['payout_trio'] * 100 if b['is_hit'] else 0
                bet_type_counts['trio'] += 1
            elif buy_as == 'st_box':
                cost = 600
                ret = b['payout_st'] * 100 if b['is_hit'] else 0
                bet_type_counts['st_box'] += 1
            elif buy_as == 'best':
                # 比較: 三連複100円 vs 三連単box600円
                # 三連複EV = model_prob × est_odds_trio
                # 三連単boxの期待値 = model_prob × est_odds_trio × ratio_median / 6
                # ratio_median ≈ 5.13 → 三連単boxは三連複の 5.13/6 = 0.855倍
                # → 三連複の方が常に有利（控除率が低い）
                # ただし予算制約がなければ三連複1点のほうがROI高い
                cost = 100
                ret = b['payout_trio'] * 100 if b['is_hit'] else 0
                bet_type_counts['trio'] += 1

            if race_invest + cost > budget:
                break
            race_invest += cost
            race_return += ret

        # 三連複の対象がないレースで単勝
        if not tr and wn:
            for b in wn[:1]:  # 単勝は最大1点
                cost = 100
                hjc_o = hjc_win.get(b['rid'],{}).get(b['combo'],0)
                ret = hjc_o * 100 if b['is_hit'] and hjc_o > 0 else 0
                if race_invest + cost > budget:
                    break
                race_invest += cost
                race_return += ret
                bet_type_counts['win'] += 1

        if race_invest == 0: continue
        total_invest += race_invest; total_return += race_return
        yr_invest[yr] += race_invest; yr_return[yr] += race_return
        n_races += 1; n_bets += race_invest // 100
        if race_return > 0:
            n_hit += 1
            if race_return < race_invest: n_hit_lose += 1

    roi = total_return / total_invest * 100 if total_invest > 0 else 0
    profit = total_return - total_invest
    yr_rois = {yr: yr_return[yr]/yr_invest[yr]*100 if yr_invest[yr]>0 else 0 for yr in [2024,2025,2026]}
    avg_bets = n_bets / n_races if n_races > 0 else 0
    avg_cost = total_invest / n_races if n_races > 0 else 0
    hit_lose = 100*n_hit_lose/n_hit if n_hit>0 else 0

    print(f"\n  {label}:")
    print(f"    R={n_races:,} bets={n_bets:,} avg={avg_bets:.1f}pt cost/R={avg_cost:.0f}円")
    print(f"    invest={total_invest:,} return={total_return:,.0f} profit={profit:+,.0f}")
    print(f"    ROI={roi:.1f}% hit_lose={hit_lose:.1f}%")
    print(f"    2024={yr_rois[2024]:.1f}% 2025={yr_rois[2025]:.1f}% 2026={yr_rois[2026]:.1f}%")
    print(f"    bet_types: {dict(bet_type_counts)}")
    return {'roi':roi,'profit':profit,'n_races':n_races,'yr_rois':yr_rois,'hit_lose':hit_lose,'avg_cost':avg_cost}

# === 各戦略をテスト ===

# 1. 三連複のみ（ベースライン、v22修正版と同じ）
print("\n--- ベースライン: 三連複のみ ---")
for ev_th in [1.0, 1.1, 1.2, 1.3]:
    for mx in [3, 5, 10]:
        sim_strategy(f"三連複 EV>={ev_th} max{mx}pt 1fav",
                     bets_trio, bets_win, ev_th, 99, 1, mx, 10000, 'trio')

# 2. 三連単ボックス（同じトリオを6点で）
print("\n--- 三連単ボックス（三連複モデルで選んだトリオ） ---")
for ev_th in [1.0, 1.2, 1.3]:
    for mx in [1, 3, 5]:
        sim_strategy(f"三連単box EV>={ev_th} max{mx}trio 1fav",
                     bets_trio, bets_win, ev_th, 99, 1, mx, 10000, 'st_box')

# 3. 三連複 + 単勝フォールバック
print("\n--- 三連複 + 単勝フォールバック ---")
for ev_th in [1.0, 1.2, 1.3]:
    sim_strategy(f"三連複EV>={ev_th} max5 + 単勝EV>=1.2 1fav",
                 bets_trio, bets_win, ev_th, 1.2, 1, 5, 10000, 'best')

# 4. 予算制限付き
print("\n--- 予算別（三連複 EV>=1.2 max5 1fav） ---")
for budget in [500, 1000, 2000, 3000, 5000, 10000]:
    sim_strategy(f"三連複 EV>=1.2 max5 budget={budget}",
                 bets_trio, bets_win, 1.2, 99, 1, 5, budget, 'trio')

# 5. 1番人気フィルタなし（参考）
print("\n--- 1番人気フィルタなし（参考） ---")
sim_strategy("三連複 EV>=1.2 max5 all_pop",
             bets_trio, bets_win, 1.2, 99, 99, 5, 10000, 'trio')

# === 月別詳細（ベスト設定） ===
print(f"\n{'='*100}")
print("月別詳細: 三連複 EV>=1.2 max5 1fav")
print(f"{'='*100}")

trio_by_race = defaultdict(list)
for b in bets_trio:
    if b['ev']>=1.2 and b['pop']<=1:
        trio_by_race[b['rid']].append(b)

monthly = defaultdict(lambda:{'invest':0,'return':0.0,'races':0,'hits':0})
for rid in trio_by_race:
    tr = sorted(trio_by_race[rid], key=lambda x:-x['ev'])[:5]
    if not tr: continue
    yr = tr[0]['year']
    rd = race_date_map.get(rid,'?')
    month = rd[:7]
    invest = len(tr) * 100
    ret = sum(b['payout_trio']*100 for b in tr if b['is_hit'])
    monthly[month]['invest'] += invest
    monthly[month]['return'] += ret
    monthly[month]['races'] += 1
    if any(b['is_hit'] for b in tr): monthly[month]['hits'] += 1

print(f"{'月':>8} | {'R':>4} | {'的中':>3} | {'投資':>9} | {'払戻':>9} | {'損益':>9} | {'ROI':>6} | {'累積':>9}")
print('-'*80)
cum=0; black=0
for m in sorted(monthly.keys()):
    v=monthly[m]; roi=v['return']/v['invest']*100 if v['invest']>0 else 0
    pnl=v['return']-v['invest']; cum+=pnl
    if pnl>0: black+=1
    print(f"{m:>8} | {v['races']:>4} | {v['hits']:>3} | {v['invest']:>8,}円 | {v['return']:>8,.0f}円 | {pnl:>+8,.0f}円 | {roi:>5.1f}% | {cum:>+8,.0f}円")
tot_m=len(monthly)
print(f"\n  黒字月: {black}/{tot_m} ({100*black/tot_m:.0f}%)")
print(f"  累積: {cum:>+,.0f}円")

print("\nDone!")
