# -*- coding: utf-8 -*-
"""検定3: 三連単モデルの周辺化
三連単モデルの順列確率を1着確率に周辺化し、単勝Δ_τと比較。

三連単モデルがP(a-b-c)を出す → Σ_{b,c} P(a-b-c) = P(a wins)
この周辺化された1着確率で条件付きロジットの対数尤度を計算し、
市場確率との差（Δ）を単勝モデルのΔと比較する。

+ 検定4: first_prob/second_prob/third_probを外した場合のA変化
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
from itertools import permutations
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
TAKEOUT = {'sanrentan': 0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c','jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5','top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_trifecta(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3; S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trifecta = {}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2); d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                trifecta[(i,j,k)]=pij*(p3[k]/d3)
    return trifecta

print("Building datasets...", flush=True)
js={}; hh={}; ts_st_stats={}

# 三連単データセット（full features と no-prob features）
st_ds = {}; STFNAMES = None
st_ds_noprob = {}; STFNAMES_NP = None

# 単勝データセット（比較用）
win_ds = {}; WFNAMES = None

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
                if tn not in ts_st_stats: ts_st_stats[tn]={'r':0,'w':0,'t3':0}
                ts_st_stats[tn]['r']+=1
                if fp==1: ts_st_stats[tn]['w']+=1
                if fp<=3: ts_st_stats[tn]['t3']+=1
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
    trifecta_mkt=sh_trifecta(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1]); rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    top1_idx=np.argmax(mp)
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
        tst=ts_st_stats.get(tn,{}); f['trainer_t3rate']=tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
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

    # 単勝データ
    if year not in win_ds: win_ds[year]={'init':[],'meta':[],'winner_idx':[]}
    winner_in_hl = hl.index(winners[0])
    win_ds[year]['init'].append(mp.copy())
    win_ds[year]['meta'].append(rid)
    win_ds[year]['winner_idx'].append(winner_in_hl)

    # 三連単データ
    if len(top3_fps)>=3:
        wst=f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        if year not in st_ds: st_ds[year]={'X':[],'y':[],'init':[],'meta':[],'sh_prob':[],'race_meta':[]}
        if year not in st_ds_noprob: st_ds_noprob[year]={'X':[],'y':[],'init':[],'meta':[],'sh_prob':[],'race_meta':[]}
        for a,b,c in permutations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            if top1_idx not in (ai,bi,ci): continue
            sh_p=trifecta_mkt.get((ai,bi,ci),0)
            if sh_p<=0: continue
            combo=f'{a}-{b}-{c}'
            pf=make_trio(a,b,c)
            pf_full = dict(pf)
            pf_full['first_prob']=mp[ai]; pf_full['second_prob']=mp[bi]; pf_full['third_prob']=mp[ci]
            if STFNAMES is None: STFNAMES=sorted(pf_full.keys())
            if STFNAMES_NP is None: STFNAMES_NP=sorted(pf.keys())
            st_ds[year]['X'].append([pf_full.get(k,0) for k in STFNAMES])
            st_ds[year]['y'].append(1 if combo==wst else 0)
            st_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            st_ds[year]['meta'].append((rid,combo,ai,bi,ci,len(hl)))
            st_ds[year]['sh_prob'].append(float(sh_p))
            # no-prob version
            st_ds_noprob[year]['X'].append([pf.get(k,0) for k in STFNAMES_NP])
            st_ds_noprob[year]['y'].append(1 if combo==wst else 0)
            st_ds_noprob[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            st_ds_noprob[year]['meta'].append((rid,combo,ai,bi,ci,len(hl)))
            st_ds_noprob[year]['sh_prob'].append(float(sh_p))
    do_update()

for ds in [st_ds, st_ds_noprob]:
    for y in sorted(ds.keys()):
        d=ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['sh_prob']=np.array(d['sh_prob'])

lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf_marginalize(ds, fnames, params, label):
    """WF→順列確率を周辺化して1着確率のΔ_τを計算"""
    print(f"\n  === {label} ===")
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

        # テストデータで順列確率を計算し、周辺化
        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; sh_te=ds[test_yr]['sh_prob']
        raw_te=model.predict(X_te,raw_score=True)

        # レース別に集約
        rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)

        # 周辺化: 各馬の1着確率 = Σ P(a-*-*) over all (b,c)
        mkt_nll = 0; model_nll = 0; n_races = 0

        for rid2, idxs in rd_te.items():
            # ys for sanrentan
            ys = y_te[idxs]
            # softmax with fix
            s = b_use * init_te[idxs] + tau_use * raw_te[idxs]
            s -= s.max()
            probs_rel = np.exp(s) / np.exp(s).sum()
            sh_sum = sh_te[idxs].sum()
            probs_abs = probs_rel * sh_sum

            # 周辺化: 馬ごとの1着確率
            # meta = (rid, combo, ai, bi, ci, n_horses)
            n_horses = meta_te[idxs[0]][5]
            win_prob_model = defaultdict(float)  # horse_idx -> P(win)
            win_prob_sh = defaultdict(float)
            for j, idx in enumerate(idxs):
                _, combo, ai, bi, ci, _ = meta_te[idx]
                # aiが1着の順列
                win_prob_model[ai] += probs_abs[j]
                win_prob_sh[ai] += sh_te[idx]

            # 1着馬を特定
            winner_combo_idx = np.where(ys == 1)[0]
            if len(winner_combo_idx) == 0: continue
            winner_ai = meta_te[idxs[winner_combo_idx[0]]][2]  # 1着のhorse_idx

            # 市場確率（3分前オッズ）
            # win_dsから取得
            if test_yr in win_ds:
                # ridで検索
                win_meta = win_ds[test_yr]['meta']
                try:
                    win_race_idx = win_meta.index(rid2)
                    market_probs = win_ds[test_yr]['init'][win_race_idx]
                    winner_idx_win = win_ds[test_yr]['winner_idx'][win_race_idx]

                    # 市場確率のNLL
                    mkt_nll -= math.log(max(market_probs[winner_idx_win], 1e-15))

                    # 周辺化モデル確率のNLL
                    # 全馬の確率に正規化
                    all_horses_model = np.zeros(n_horses)
                    for hidx, p in win_prob_model.items():
                        if hidx < n_horses: all_horses_model[hidx] = p
                    # 上位8頭以外は市場確率で補完
                    for hidx in range(n_horses):
                        if all_horses_model[hidx] == 0:
                            all_horses_model[hidx] = market_probs[hidx] * (1 - all_horses_model.sum()) / max(1 - sum(market_probs[h] for h in win_prob_model), 1e-10) if sum(market_probs[h] for h in win_prob_model) < 1 else 0
                    # 再正規化
                    total = all_horses_model.sum()
                    if total > 0: all_horses_model /= total
                    model_nll -= math.log(max(all_horses_model[winner_idx_win], 1e-15))
                    n_races += 1
                except (ValueError, IndexError):
                    continue

        if n_races > 0:
            delta = (mkt_nll - model_nll) / n_races
            print(f"    {test_yr}: n_races={n_races}, mkt_NLL/R={mkt_nll/n_races:.4f}, model_NLL/R={model_nll/n_races:.4f}, Delta={delta:+.5f}")

# 単勝のΔ_τ（参考、v16相当）
print(f"\n{'='*80}")
print("検定3: 周辺化Δ_τ")
print(f"{'='*80}")

# まず単勝のΔ（市場のみ vs v16モデル）を計算
print("\n  === 単勝 Δ_τ（参考） ===")
# 単勝のWFは別途計算が必要だが、MEMORYから: Δ_τ ≈ +0.001〜+0.012
print("  (MEMORY: v16 Delta_tau = +0.001 to +0.012 per year)")

# 三連単モデルの周辺化
run_wf_marginalize(st_ds, STFNAMES, lgb_p, "三連単 full features (with first/second/third_prob)")
run_wf_marginalize(st_ds_noprob, STFNAMES_NP, lgb_p, "三連単 no-prob features (without first/second/third_prob)")

# 検定4: 特徴量の寄与
print(f"\n{'='*80}")
print("検定4: first/second/third_probの影響")
print(f"{'='*80}")
print(f"  full features:    {STFNAMES}")
print(f"  no-prob features: {STFNAMES_NP}")
print(f"  removed: {set(STFNAMES) - set(STFNAMES_NP)}")

# A値比較（EV>=1.2のhit-rateベース、簡易版）
def compute_A(ds, fnames, params, label):
    print(f"\n  {label}:")
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

        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; sh_te=ds[test_yr]['sh_prob']
        odds_te = (1/sh_te) * (1-TAKEOUT['sanrentan'])
        raw_te=model.predict(X_te,raw_score=True); rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
        n_ev12=0; hit_ev12=0; sum_est_hit=0
        for rid2,idxs in rd_te.items():
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            pr=np.exp(s)/np.exp(s).sum(); sh_sum=sh_te[idxs].sum()
            pa=pr*sh_sum
            for j,idx in enumerate(idxs):
                ev=pa[j]*odds_te[idx]
                if ev>=1.2:
                    n_ev12+=1
                    if y_te[idx]:
                        hit_ev12+=1; sum_est_hit+=odds_te[idx]*100
        A=sum_est_hit/(n_ev12*100) if n_ev12>0 else 0
        print(f"    {test_yr}: b={b_use:.3f} tau={tau_use:.3f} n_EV12={n_ev12:,} hit={hit_ev12} A={A*100:.1f}%")

        # feature importance
        imp=model.feature_importance(importance_type='gain')
        fi=sorted(zip(fnames,imp),key=lambda x:-x[1])
        print(f"      top5: {', '.join(f'{n}={v:.0f}' for n,v in fi[:5])}")

compute_A(st_ds, STFNAMES, lgb_p, "三連単 full (with prob)")
compute_A(st_ds_noprob, STFNAMES_NP, lgb_p, "三連単 no-prob")

print("\nDone!")
