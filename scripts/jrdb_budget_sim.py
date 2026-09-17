# -*- coding: utf-8 -*-
"""1R予算別シミュレーション
三連複+三連単ポートフォリオで、1R予算を変えたときの
点数・投資額・回収率・損益をシミュレーション

v22のWF結果を使い、レース単位で集計
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
TAKEOUT = {'sanrenpuku': 0.25, 'sanrentan': 0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']

def stern_harville_full(p):
    n = len(p); p2 = p**LAM2; p3 = p**LAM3
    S1 = p.sum(); S2 = p2.sum(); S3 = p3.sum()
    umaren = defaultdict(float); umatan = {}
    trio = defaultdict(float); trifecta = {}
    for i in range(n):
        d2 = S2 - p2[i]
        if d2 <= 0: continue
        for j in range(n):
            if j == i: continue
            pij = (p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))] += pij
            umatan[(i,j)] = pij
            d3 = S3 - p3[i] - p3[j]
            if d3 <= 0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk = pij*(p3[k]/d3)
                trio[tuple(sorted([i,j,k]))] += pijk
                trifecta[(i,j,k)] = pijk
    return umaren, umatan, trio, trifecta

# === Build datasets (trio + sanrentan only) ===
print("Building...", flush=True)
js = {}; hh = {}; ts_st = {}
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
    _,_,trio_mkt,trifecta_mkt = stern_harville_full(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    top1_idx = np.argmax(mp)

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

    # 三連複
    if len(top3_fps)>=3:
        wtr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in tr_ds: tr_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'rid':[]}
        for a,b,c in combinations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            key=tuple(sorted([ai,bi,ci]))
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
            tr_ds[year]['rid'].append(rid)

    # 三連単（1番人気含む）
    if len(top3_fps)>=3:
        wst=f'{top3_fps[0]["hn"]}-{top3_fps[1]["hn"]}-{top3_fps[2]["hn"]}'
        if year not in st_ds: st_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'rid':[]}
        for a,b,c in permutations(top8,3):
            ai,bi,ci=hl.index(a),hl.index(b),hl.index(c)
            if top1_idx not in (ai,bi,ci): continue
            sh_p=trifecta_mkt.get((ai,bi,ci),0)
            if sh_p<=0: continue
            combo=f'{a}-{b}-{c}'
            pf=make_trio_f(a,b,c)
            pf['first_prob']=mp[ai]; pf['second_prob']=mp[bi]; pf['third_prob']=mp[ci]
            if STFNAMES is None: STFNAMES=sorted(pf.keys())
            st_ds[year]['X'].append([pf.get(k,0) for k in STFNAMES])
            st_ds[year]['y'].append(1 if combo==wst else 0)
            st_ds[year]['init'].append(math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15)))
            st_ds[year]['meta'].append((rid,combo))
            st_ds[year]['odds'].append((1/sh_p)*(1-TAKEOUT['sanrentan']))
            st_ds[year]['pop'].append(min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99)))
            st_ds[year]['rid'].append(rid)
    do_update()

for ds_name, ds_obj in [('trio',tr_ds),('sanrentan',st_ds)]:
    for y in sorted(ds_obj.keys()):
        d=ds_obj[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
        d['pop']=np.array(d['pop']); d['rid']=np.array(d['rid'])
    sizes=', '.join(str(y)+':'+str(len(ds_obj[y]['X'])) for y in sorted(ds_obj.keys()))
    print(f"  {ds_name}: {sizes}")

lgb_p = {'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
         'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
         'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf_bets(ds, fnames, params, hjc_type):
    """WF → レースID付きベットリストを返す"""
    all_bets = []
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
        pop_te=ds[test_yr]['pop']; rid_te=ds[test_yr]['rid']
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
                pop_val=int(pop_te[idx])
                all_bets.append({'rid':rid2,'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'odds':o,'pop':pop_val,'combo':combo,'prob':float(probs[j])})
    return all_bets

print("Running WF...", flush=True)
bets_trio = run_wf_bets(tr_ds, TRFNAMES, lgb_p, 'sanrenpuku_hjc')
bets_st = run_wf_bets(st_ds, STFNAMES, lgb_p, 'sanrentan_hjc')
print(f"  trio: {len(bets_trio):,}, sanrentan: {len(bets_st):,}")

# === 1R予算別シミュレーション ===
print(f"\n{'='*120}")
print("1R予算別シミュレーション（三連複+三連単ポートフォリオ、1番人気含む、EV>=1.2）")
print(f"{'='*120}")

# レース別にベットを整理
EV_TH = 1.2
race_bets = defaultdict(lambda: {'trio': [], 'st': []})
for b in bets_trio:
    if b['ev'] >= EV_TH and b['pop'] <= 1:
        race_bets[b['rid']]['trio'].append(b)
for b in bets_st:
    if b['ev'] >= EV_TH and b['pop'] <= 1:
        race_bets[b['rid']]['st'].append(b)

# レース日付マップ
race_date_map = {r[0]: r[1] for r in races_raw}
race_venue_map = {}
for r in races_raw:
    race_venue_map[r[0]] = r[2]  # venue_code

# 有効なレース（少なくとも1点ある）
active_races = {rid: rb for rid, rb in race_bets.items() if rb['trio'] or rb['st']}
print(f"Active races: {len(active_races):,}")

# 1Rあたりの点数分布
n_bets_per_race = []
for rid, rb in active_races.items():
    n = len(rb['trio']) + len(rb['st'])
    n_bets_per_race.append(n)
n_arr = np.array(n_bets_per_race)
print(f"\n=== 1Rあたりの点数分布 ===")
print(f"  mean: {np.mean(n_arr):.1f}, median: {np.median(n_arr):.0f}")
print(f"  min: {np.min(n_arr)}, max: {np.max(n_arr)}")
for pct in [10, 25, 50, 75, 90, 95, 99]:
    print(f"  {pct}%ile: {np.percentile(n_arr, pct):.0f}")

# 券種別の内訳
n_trio_per = [len(rb['trio']) for rb in active_races.values()]
n_st_per = [len(rb['st']) for rb in active_races.values()]
print(f"\n  三連複: mean={np.mean(n_trio_per):.1f}, median={np.median(n_trio_per):.0f}")
print(f"  三連単: mean={np.mean(n_st_per):.1f}, median={np.median(n_st_per):.0f}")

# === 予算別シミュレーション ===
budgets = [500, 1000, 2000, 3000, 5000, 10000]

print(f"\n{'='*120}")
print(f"{'予算':>8} | {'1点単価':>8} | {'avg点数':>8} | {'ベットR':>7} | {'総投資':>12} | {'総払戻':>12} | {'利益':>12} | {'ROI':>6} | {'2024':>7} {'2025':>7} {'2026':>7}")
print('-' * 120)

for budget in budgets:
    yr_invest = defaultdict(int)
    yr_return = defaultdict(float)
    total_invest = 0
    total_return = 0.0
    n_races_bet = 0
    total_bets = 0

    for rid, rb in active_races.items():
        all_cands = rb['trio'] + rb['st']
        if not all_cands:
            continue

        n_cands = len(all_cands)
        # 1点あたりの金額（100円単位切り下げ）
        per_bet = max(100, (budget // n_cands // 100) * 100)

        # 予算超過チェック: 点数が多すぎる場合はEV上位に絞る
        if per_bet * n_cands > budget * 1.5:
            # EV上位で予算内に収める
            all_cands.sort(key=lambda x: -x['ev'])
            max_n = budget // 100
            all_cands = all_cands[:max_n]
            n_cands = len(all_cands)
            per_bet = 100

        yr = all_cands[0]['year']
        race_invest = n_cands * per_bet
        race_return = 0.0
        for b in all_cands:
            if b['is_hit']:
                race_return += b['payout'] * per_bet

        total_invest += race_invest
        total_return += race_return
        yr_invest[yr] += race_invest
        yr_return[yr] += race_return
        n_races_bet += 1
        total_bets += n_cands

    roi = total_return / total_invest * 100 if total_invest > 0 else 0
    profit = total_return - total_invest
    avg_bets = total_bets / n_races_bet if n_races_bet > 0 else 0
    avg_per_bet = total_invest / total_bets if total_bets > 0 else 0

    yr_parts = []
    for yr in [2024, 2025, 2026]:
        if yr_invest[yr] > 0:
            yr_parts.append(f'{yr_return[yr]/yr_invest[yr]*100:>6.1f}%')
        else:
            yr_parts.append('     -')

    print(f'{budget:>7,}円 | {avg_per_bet:>7.0f}円 | {avg_bets:>7.1f} | {n_races_bet:>6,}R | {total_invest:>11,}円 | {total_return:>11,.0f}円 | {profit:>+11,.0f}円 | {roi:>5.1f}% | {" ".join(yr_parts)}')

# === 1R予算1000円の詳細サンプル ===
print(f"\n{'='*120}")
print("1R予算1,000円のサンプルレース（2026年、最初の20R）")
print(f"{'='*120}")

budget = 1000
sample_races = []
for rid, rb in sorted(active_races.items(), key=lambda x: x[0]):
    all_cands = rb['trio'] + rb['st']
    if not all_cands: continue
    yr = all_cands[0]['year']
    if yr != 2026: continue
    sample_races.append((rid, rb))
    if len(sample_races) >= 20:
        break

print(f"{'RID':>10} | {'日付':>10} | {'三連複':>4} {'三連単':>4} {'計':>3} | {'1点':>5} | {'投資':>7} | {'払戻':>8} | {'損益':>8} | {'top_combo':>16} {'EV':>5}")
print('-' * 110)

for rid, rb in sample_races:
    all_cands = rb['trio'] + rb['st']
    n_cands = len(all_cands)
    per_bet = max(100, (budget // n_cands // 100) * 100)
    if per_bet * n_cands > budget * 1.5:
        all_cands.sort(key=lambda x: -x['ev'])
        max_n = budget // 100
        all_cands = all_cands[:max_n]
        n_cands = len(all_cands)
        per_bet = 100

    invest = n_cands * per_bet
    payout = sum(b['payout'] * per_bet for b in all_cands if b['is_hit'])
    profit = payout - invest
    n_trio = sum(1 for b in all_cands if 'trio' in str(type(b)) or '-' in b['combo'] and b['combo'].count('-') == 2 and b['combo'] == '-'.join(sorted(b['combo'].split('-'))))
    # 簡易判定: 三連複はcomboがソート済み
    n_trio_actual = len(rb['trio'])
    n_st_actual = len(rb['st'])
    top = max(all_cands, key=lambda x: x['ev'])
    rd = race_date_map.get(rid, '?')
    mark = '***' if payout > 0 else ''
    print(f'{rid:>10} | {rd:>10} | {n_trio_actual:>4} {n_st_actual:>4} {n_cands:>3} | {per_bet:>4}円 | {invest:>6,}円 | {payout:>7,.0f}円 | {profit:>+7,.0f}円 | {top["combo"]:>16} {top["ev"]:>5.2f} {mark}')

# === 月別損益（1R予算1000円） ===
print(f"\n{'='*120}")
print("月別損益（1R予算1,000円）")
print(f"{'='*120}")

budget = 1000
monthly = defaultdict(lambda: {'invest': 0, 'return': 0.0, 'races': 0, 'hits': 0})
for rid, rb in active_races.items():
    all_cands = rb['trio'] + rb['st']
    if not all_cands: continue
    n_cands = len(all_cands)
    per_bet = max(100, (budget // n_cands // 100) * 100)
    if per_bet * n_cands > budget * 1.5:
        all_cands.sort(key=lambda x: -x['ev'])
        all_cands = all_cands[:budget // 100]
        n_cands = len(all_cands)
        per_bet = 100

    rd = race_date_map.get(rid, '2024-01-01')
    month = rd[:7]
    invest = n_cands * per_bet
    payout = sum(b['payout'] * per_bet for b in all_cands if b['is_hit'])
    monthly[month]['invest'] += invest
    monthly[month]['return'] += payout
    monthly[month]['races'] += 1
    monthly[month]['hits'] += sum(1 for b in all_cands if b['is_hit'])

print(f"{'月':>8} | {'R数':>5} | {'的中':>4} | {'投資':>10} | {'払戻':>10} | {'損益':>10} | {'ROI':>6} | {'累積損益':>10}")
print('-' * 90)
cum_pnl = 0
for month in sorted(monthly.keys()):
    m = monthly[month]
    roi = m['return'] / m['invest'] * 100 if m['invest'] > 0 else 0
    pnl = m['return'] - m['invest']
    cum_pnl += pnl
    print(f'{month:>8} | {m["races"]:>5} | {m["hits"]:>4} | {m["invest"]:>9,}円 | {m["return"]:>9,.0f}円 | {pnl:>+9,.0f}円 | {roi:>5.1f}% | {cum_pnl:>+9,.0f}円')

print(f"\n  Total: invest={sum(m["invest"] for m in monthly.values()):,}円, return={sum(m["return"] for m in monthly.values()):,.0f}円, PnL={cum_pnl:>+,.0f}円")

print("\nDone!")
