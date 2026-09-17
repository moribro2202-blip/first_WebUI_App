# -*- coding: utf-8 -*-
"""良い所どり分析: 券種間の重複・相関・ポートフォリオ最適化
jrdb_all_bet_types.py と同じデータ構築 → ポートフォリオ分析
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
    if hs:
        race_horses[rid] = sorted(hs)
ts_odds = {}
for mb in [0, 1, 2, 3, 5, 10]:
    ts_odds[mb] = defaultdict(dict)
    for rid, hn, odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=? AND odds>0', (mb,)).fetchall():
        ts_odds[mb][rid][hn] = odds
sed = defaultdict(dict)
for row in db.execute('SELECT race_id,horse_number,win_odds FROM results WHERE win_odds IS NOT NULL AND win_odds>0').fetchall():
    sed[row[0]][row[1]] = row[2]
oz_cache = {}
for rid, _, _, _, _ in races_raw:
    oz = db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'", (rid,)).fetchall()
    if oz:
        oz_cache[rid] = {int(r[0]): r[1] for r in oz}
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]
cyb_cache = {}
for fpath in sorted(glob.glob(os.path.join(JRDB, 'CYB', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 38: continue
            raw = line.decode('ascii', 'replace')
            rid2 = f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
            try:
                hn_i = int(raw[8:10]); score = int(raw[33:35].strip())
            except: continue
            cyb_cache[(rid2, hn_i)] = score
db.close()
print("Loaded.", flush=True)

LAM2, LAM3 = 0.8076, 0.6978
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}
TAKEOUT = {'win':0.20,'umatan':0.225,'umaren':0.225,'sanrentan':0.2725,'sanrenpuku':0.25,'wide':0.225}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']

def stern_harville_full(p):
    n = len(p); p2 = p**LAM2; p3 = p**LAM3
    S1 = p.sum(); S2 = p2.sum(); S3 = p3.sum()
    umatan = {}; umaren = defaultdict(float); sanrentan = {}
    trio = defaultdict(float); wide = defaultdict(float)
    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0: continue
        for j in range(n):
            if j == i: continue
            pij = (p[i]/S1)*(p2[j]/d2)
            umatan[(i,j)] = pij
            umaren[tuple(sorted([i,j]))] += pij
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk = pij*(p3[k]/d3)
                sanrentan[(i,j,k)] = pijk
                trio[tuple(sorted([i,j,k]))] += pijk
    for key, p_val in trio.items():
        i, j, k = key
        wide[(i,j)] = wide.get((i,j),0) + p_val
        wide[(i,k)] = wide.get((i,k),0) + p_val
        wide[(j,k)] = wide.get((j,k),0) + p_val
    return umatan, umaren, sanrentan, trio, wide

# === Build all data + run WF in one pass, collecting per-race bets ===
print("Building...", flush=True)
js = {}; hh = {}; ts_st = {}

# Store all bets indexed by (rid, bet_type)
# Each bet: {rid, year, bet_type, ev, is_hit, payout, odds, pop, combo}
all_race_bets = defaultdict(list)  # rid -> list of bets

# We need to run WF first to get model predictions
# Simplified: build datasets, run WF, collect bets with rid

# --- reuse v21 framework ---
win_ds = {}; WFNAMES = None
um_ds = {}; UMFNAMES = None
ut_ds = {}; UTFNAMES = None
tr_ds = {}; TRFNAMES = None
st_ds = {}; STFNAMES = None

for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
    def do_update():
        for res in result_cache.get(rid,[]):
            hn,fp,hid = res['hn'],res['fp'],res['hid']
            ent = entry_cache.get(rid,{}).get(hn,{})
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
    if year < 2022: do_update(); continue
    hl = race_horses.get(rid,[])
    if len(hl)<5: do_update(); continue
    rl = result_cache.get(rid,[])
    if not rl: do_update(); continue
    winners = [r['hn'] for r in rl if r['fp']==1]
    if not winners or winners[0] not in hl: do_update(); continue

    o3=ts_odds[3].get(rid,{}); o5=ts_odds[5].get(rid,{})
    odds_mkt = o3 if len(o3)>=len(hl)*0.8 else sed.get(rid,{})
    has_move = len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
    entries=entry_cache.get(rid,{}); n=len(hl)
    inv_arr=np.array([1/odds_mkt.get(h,999) for h in hl])
    s=inv_arr.sum()
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
    fps=result_full.get(rid,{})
    hjc=hjc_all.get(rid,{})
    umatan_mkt,umaren_mkt,sanrentan_mkt,trio_mkt,wide_mkt = stern_harville_full(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}

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
        f['win_odds_3min']=o3.get(h,0); f['win_prob']=mp[i]
        feats_h[h]=f

    # 単勝
    if year not in win_ds: win_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    for i,h in enumerate(hl):
        if WFNAMES is None: WFNAMES=sorted(FEAT_KEYS)
        win_ds[year]['X'].append([feats_h[h].get(k,0) for k in WFNAMES])
        win_ds[year]['y'].append(1 if h==winners[0] else 0)
        win_ds[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        win_ds[year]['meta'].append((rid,h))
        win_ds[year]['odds'].append(o3.get(h,0))

    top8=[h for h,_ in sorted(odds_mkt.items(),key=lambda x:x[1])[:8]] if odds_mkt else hl[:8]
    top2_fps=sorted([r for r in rl if r['fp'] in (1,2)],key=lambda x:x['fp'])
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])

    def make_pair(a,b):
        pf={}; f1=feats_h[a]; f2=feats_h[b]
        for k in FEAT_KEYS: pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0); pf[f'{k}_diff']=abs(f1.get(k,0)-f2.get(k,0))
        ow1=f1.get('win_odds_3min',0); ow2=f2.get('win_odds_3min',0)
        pf['win_odds_ratio']=min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
        pf['win_odds_sum_inv']=(1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
        return pf
    def make_trio_f(a,b,c):
        pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1,v2,v3=f1.get(k,0),f2.get(k,0),f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        ol=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=ol[0]/ol[-1] if len(ol)>=2 and ol[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in ol if o>0)
        return pf

    # 馬連
    if len(top2_fps)>=2:
        wum='-'.join(str(x) for x in sorted([top2_fps[0]['hn'],top2_fps[1]['hn']]))
        if year not in um_ds: um_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
        for a,b in combinations(top8,2):
            ai=hl.index(a); bi=hl.index(b); key=tuple(sorted([ai,bi]))
            sh_p=umaren_mkt.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b]))
            pf=make_pair(a,b)
            if UMFNAMES is None: UMFNAMES=sorted(pf.keys())
            um_ds[year]['X'].append([pf.get(k,0) for k in UMFNAMES])
            um_ds[year]['y'].append(1 if combo==wum else 0)
            um_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            um_ds[year]['meta'].append((rid,combo))
            um_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['umaren']))
            um_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99)))

    # 三連複
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
            tr_ds[year]['meta'].append((rid,combo))
            tr_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrenpuku']))
            tr_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))

    # 三連単
    if len(top3_fps)>=3:
        wst=f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        if year not in st_ds: st_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
        for a,b,c in permutations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            sh_p=sanrentan_mkt.get((ai,bi,ci),0)
            if sh_p<=0: continue
            combo=f'{a}-{b}-{c}'
            pf=make_trio_f(a,b,c)
            pf['first_prob']=feats_h[a].get('win_prob',0)
            pf['second_prob']=feats_h[b].get('win_prob',0)
            pf['third_prob']=feats_h[c].get('win_prob',0)
            if STFNAMES is None: STFNAMES=sorted(pf.keys())
            st_ds[year]['X'].append([pf.get(k,0) for k in STFNAMES])
            st_ds[year]['y'].append(1 if combo==wst else 0)
            st_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            st_ds[year]['meta'].append((rid,combo))
            st_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrentan']))
            st_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
    do_update()

for ds_name, ds_obj in [('win',win_ds),('umaren',um_ds),('trio',tr_ds),('sanrentan',st_ds)]:
    for y in sorted(ds_obj.keys()):
        d=ds_obj[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        if 'pop' in d: d['pop']=np.array(d['pop'])
    sizes=', '.join(str(y)+':'+str(len(ds_obj[y]['X'])) for y in sorted(ds_obj.keys()))
    print(f"  {ds_name}: {sizes}")

# === WF ===
lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf_collect(ds, fnames, params, label, hjc_type):
    """WF実行、レースIDつきでベット情報を返す"""
    print(f"  WF: {label}", flush=True)
    all_bets=[]
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in ds]; fit_yr=test_yr-1
        if not train_yrs or fit_yr not in ds or test_yr not in ds: continue
        X_tr=np.vstack([ds[y]['X'] for y in train_yrs])
        y_tr=np.concatenate([ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([ds[y]['init'] for y in train_yrs])
        model=lgb.train(params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
        X_f=ds[fit_yr]['X']; y_f=ds[fit_yr]['y']; init_f=ds[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,m in enumerate(ds[fit_yr]['meta']): rd_f[m[0]].append(i)
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
        X_te=ds[test_yr]['X']; y_te=ds[test_yr]['y']; init_te=ds[test_yr]['init']
        meta_te=ds[test_yr]['meta']; odds_te=ds[test_yr]['odds']
        pop_te=ds[test_yr].get('pop',np.zeros(len(y_te)))
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,m in enumerate(meta_te): rd_te[m[0]].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; o=odds_te[idx]; ev=probs[j]*o
                is_hit=y_te[idx]
                payout=hjc_all.get(rid2,{}).get(hjc_type,{}).get(str(combo) if isinstance(combo,int) else combo,0) if is_hit else 0
                pop_val=int(pop_te[idx]) if len(pop_te)>idx else 0
                all_bets.append({'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'odds':o,'pop':pop_val,'combo':combo})
    return all_bets

print("\nRunning WF...", flush=True)
bw = run_wf_collect(win_ds, WFNAMES, lgb_w, "win", 'win_hjc')
bu = run_wf_collect(um_ds, UMFNAMES, lgb_p, "umaren", 'umaren_hjc')
bt = run_wf_collect(tr_ds, TRFNAMES, lgb_p, "trio", 'sanrenpuku_hjc')
bs = run_wf_collect(st_ds, STFNAMES, lgb_p, "sanrentan", 'sanrentan_hjc')

# === ポートフォリオ分析 ===
print(f"\n{'='*100}")
print("Portfolio Analysis")
print(f"{'='*100}")

# 各券種のEV>=1.2, 1番人気含むベットをレース別に整理
def filter_bets(bets, ev_th=1.2, pop_max=1, odds_lo=0, odds_hi=9999):
    return [b for b in bets if b['ev']>=ev_th and b.get('pop',99)<=pop_max and odds_lo<=b['odds']<=odds_hi]

win_f = [b for b in bw if b['ev']>=1.2 and 2<=b['odds']<=40]  # 単勝は人気フィルタなし
um_f = filter_bets(bu, 1.2, 1)
tr_f = filter_bets(bt, 1.2, 1)
st_f = filter_bets(bs, 1.2, 1)

# レース別ベット数
race_bets = defaultdict(lambda: {'win':[], 'umaren':[], 'trio':[], 'sanrentan':[]})
for b in win_f: race_bets[b['rid']]['win'].append(b)
for b in um_f: race_bets[b['rid']]['umaren'].append(b)
for b in tr_f: race_bets[b['rid']]['trio'].append(b)
for b in st_f: race_bets[b['rid']]['sanrentan'].append(b)

# 1. レース別の券種カバレッジ
print(f"\n=== 1. レース別 券種カバレッジ ===")
all_rids = set(race_bets.keys())
print(f"  Total races with any EV>=1.2 bet: {len(all_rids):,}")
for bt_name in ['win','umaren','trio','sanrentan']:
    rids_with = set(rid for rid in all_rids if race_bets[rid][bt_name])
    print(f"  {bt_name:>10}: {len(rids_with):,} races ({100*len(rids_with)/len(all_rids):.1f}%)")

# 券種の組み合わせ
from itertools import product as iprod
combo_counts = defaultdict(int)
for rid in all_rids:
    key = tuple(1 if race_bets[rid][bt] else 0 for bt in ['win','umaren','trio','sanrentan'])
    combo_counts[key] += 1
print(f"\n  Combination (win,umaren,trio,sanrentan):")
for key in sorted(combo_counts.keys(), key=lambda x: -combo_counts[x]):
    labels = [bt for bt, v in zip(['win','umaren','trio','sanrentan'], key) if v]
    print(f"    {key} = {'+'.join(labels) if labels else 'none'}: {combo_counts[key]:,} races")

# 2. 的中の相関
print(f"\n=== 2. 同一レース内の的中相関 ===")
# レースごとに、各券種で少なくとも1つ的中したかを集計
for bt_a, bt_b in [('trio','sanrentan'),('trio','umaren'),('trio','win'),
                    ('sanrentan','umaren'),('sanrentan','win'),('umaren','win')]:
    rids_both = [rid for rid in all_rids if race_bets[rid][bt_a] and race_bets[rid][bt_b]]
    if not rids_both: continue
    hit_a = sum(1 for rid in rids_both if any(b['is_hit'] for b in race_bets[rid][bt_a]))
    hit_b = sum(1 for rid in rids_both if any(b['is_hit'] for b in race_bets[rid][bt_b]))
    hit_both = sum(1 for rid in rids_both if any(b['is_hit'] for b in race_bets[rid][bt_a]) and any(b['is_hit'] for b in race_bets[rid][bt_b]))
    n = len(rids_both)
    print(f"  {bt_a:>10}+{bt_b:<10}: {n:>5,} races, "
          f"hit_a={100*hit_a/n:.1f}%, hit_b={100*hit_b/n:.1f}%, "
          f"hit_both={100*hit_both/n:.1f}%, "
          f"P(b|a)={100*hit_both/hit_a:.1f}%" if hit_a>0 else "")

# 3. ポートフォリオシミュレーション
print(f"\n=== 3. ポートフォリオシミュレーション (固定100円/点) ===")

# 各戦略の定義
strategies = {
    'S1: 三連複1番のみ': lambda rb: rb['trio'],
    'S2: 三連単1番のみ': lambda rb: rb['sanrentan'],
    'S3: 単勝のみ': lambda rb: rb['win'],
    'S4: 三連複+三連単': lambda rb: rb['trio'] + rb['sanrentan'],
    'S5: 三連複+馬連': lambda rb: rb['trio'] + rb['umaren'],
    'S6: 三連複+三連単+馬連': lambda rb: rb['trio'] + rb['sanrentan'] + rb['umaren'],
    'S7: 全券種': lambda rb: rb['win'] + rb['umaren'] + rb['trio'] + rb['sanrentan'],
    'S8: 三連複+単勝': lambda rb: rb['trio'] + rb['win'],
}

print(f"\n  {'Strategy':>30s} | {'n_bets':>7s} {'n_races':>7s} | {'invest':>10s} {'return':>10s} {'profit':>10s} {'ROI':>7s} | {'2024':>7s} {'2025':>7s} {'2026':>7s}")
print(f"  {'-'*120}")

for sname, sfunc in strategies.items():
    total_invest = 0; total_return = 0
    yr_invest = defaultdict(int); yr_return = defaultdict(float)
    n_bets = 0; n_races = 0
    for rid in all_rids:
        bets = sfunc(race_bets[rid])
        if not bets: continue
        n_races += 1
        for b in bets:
            n_bets += 1
            total_invest += 100
            yr_invest[b['year']] += 100
            if b['is_hit']:
                total_return += b['payout'] * 100
                yr_return[b['year']] += b['payout'] * 100
    roi = total_return / total_invest * 100 if total_invest > 0 else 0
    profit = total_return - total_invest
    yr_parts = []
    for yr in [2024, 2025, 2026]:
        if yr_invest[yr] > 0:
            yr_parts.append(f'{yr_return[yr]/yr_invest[yr]*100:>6.1f}%')
        else:
            yr_parts.append('     -')
    print(f"  {sname:>30s} | {n_bets:>7,} {n_races:>7,} | {total_invest:>10,} {total_return:>10,.0f} {profit:>+10,.0f} {roi:>6.1f}% | {' '.join(yr_parts)}")

# 4. 最適EV閾値の組み合わせ
print(f"\n=== 4. 券種別EV閾値の最適化 ===")
best_roi = 0; best_config = None
for tr_th in [1.0, 1.1, 1.2, 1.3]:
    for st_th in [1.0, 1.1, 1.2, 1.3]:
        tr_f2 = filter_bets(bt, tr_th, 1)
        st_f2 = filter_bets(bs, st_th, 1)
        rb2 = defaultdict(lambda: {'trio':[], 'sanrentan':[]})
        for b in tr_f2: rb2[b['rid']]['trio'].append(b)
        for b in st_f2: rb2[b['rid']]['sanrentan'].append(b)
        ti = 0; tr_val = 0
        for rid in rb2:
            for b in rb2[rid]['trio'] + rb2[rid]['sanrentan']:
                ti += 100
                if b['is_hit']: tr_val += b['payout'] * 100
        if ti > 0:
            roi = tr_val / ti * 100
            n = ti // 100
            if roi > best_roi:
                best_roi = roi; best_config = (tr_th, st_th, n, roi)
            print(f"  trio>={tr_th:.1f} + sanrentan>={st_th:.1f}: n={n:>8,} ROI={roi:>6.1f}%")

if best_config:
    print(f"\n  BEST: trio>={best_config[0]:.1f} + sanrentan>={best_config[1]:.1f}: n={best_config[2]:,} ROI={best_config[3]:.1f}%")

print("\nDone!")
