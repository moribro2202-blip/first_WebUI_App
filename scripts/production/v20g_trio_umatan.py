# -*- coding: utf-8 -*-
"""v20g: 三連複・馬単 プール直接基準 + move_5to3
馬連v20と同じアーキテクチャ:
  市場確率: confirmed_oddsから直接算出
  残差: ペア/トリオレベル特徴量でLightGBM
  強さ: s = b × ln(π_pool) + τ × r
"""
import sqlite3, math, sys, os, glob, numpy as np, lightgbm as lgb
from collections import defaultdict
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

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']

def build_horse_feat(h, entries, hl, avg_idm, avg_rider, oz_inv, oz_sum, mk_inv, mk_sum,
                     avg_cyb, js, ts_st, hh, o5, o3, has_move, cyb_cache, rid):
    ent = entries.get(h, {}); hid = ent.get('hid', '')
    f = {}
    f['idm_c'] = (ent.get('idm') or 50) - avg_idm
    f['rider_c'] = (ent.get('rider') or 0) - avg_rider
    f['total_index'] = ent.get('total') or 0
    oz_p = oz_inv.get(h,0)/oz_sum; mk_p = mk_inv.get(h,0)/mk_sum
    f['expert_resid'] = math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
    f['cyb_c'] = cyb_cache.get((rid,h),0) - avg_cyb
    jn = ent.get('jockey',''); tn = ent.get('trainer','')
    jst = js.get(jn,{}); f['jockey_t3rate'] = jst.get('t3',0)/jst['r'] if jst.get('r',0)>=30 else -1
    tst = ts_st.get(tn,{}); f['trainer_t3rate'] = tst.get('t3',0)/tst['r'] if tst.get('r',0)>=30 else -1
    runs = hh.get(hid, [])
    f['horse_runs'] = len(runs)
    if runs:
        rc = runs[-5:]; f['avg_fp_5'] = np.mean([r['fp'] for r in rc])
        f['top3_rate'] = sum(1 for r in runs if r['fp']<=3)/len(runs)
        f['last_fp'] = runs[-1]['fp']
        f['win_rate'] = sum(1 for r in runs if r['fp']==1)/len(runs) if len(runs)>=5 else -1
    else:
        f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
    f['is_senkou'] = 1 if ent.get('run_style','') in ('逃げ','先行') else 0
    if has_move:
        oo5 = o5.get(h,0); oo3 = o3.get(h,0)
        f['move_5to3'] = (oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
    else: f['move_5to3'] = 0
    f['win_odds_3min'] = o3.get(h,0)
    return f

def make_pair_features(f1, f2):
    pf = {}
    for key in FEAT_KEYS:
        v1 = f1.get(key,0); v2 = f2.get(key,0)
        pf[f'{key}_sum'] = v1 + v2; pf[f'{key}_diff'] = abs(v1 - v2)
    ow1 = f1.get('win_odds_3min',0); ow2 = f2.get('win_odds_3min',0)
    pf['win_odds_ratio'] = min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
    pf['win_odds_sum_inv'] = (1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
    return pf

def make_trio_features(f1, f2, f3):
    pf = {}
    for key in FEAT_KEYS:
        v1 = f1.get(key,0); v2 = f2.get(key,0); v3 = f3.get(key,0)
        pf[f'{key}_sum'] = v1 + v2 + v3
        pf[f'{key}_spread'] = max(v1,v2,v3) - min(v1,v2,v3)
    ow1 = f1.get('win_odds_3min',0); ow2 = f2.get('win_odds_3min',0); ow3 = f3.get('win_odds_3min',0)
    odds_list = sorted([o for o in [ow1,ow2,ow3] if o>0])
    pf['win_odds_top_ratio'] = odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
    pf['win_odds_sum_inv'] = sum(1/o for o in odds_list if o>0)
    return pf

# === データセット構築 ===
print("Building datasets...", flush=True)
js={}; hh={}; ts_st={}
# 券種別データセット
ds = {'umatan':{}, 'trio':{}}
FNAMES = {'umatan':None, 'trio':None}

cdb = sqlite3.connect(DB, timeout=30)
n_proc = 0
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
    if year < 2022: do_update(); continue
    hl = race_horses.get(rid, [])
    if len(hl) < 5: do_update(); continue

    o5 = ts5.get(rid,{}); o3 = ts3.get(rid,{})
    odds_mkt = o3 if len(o3)>=len(hl)*0.8 else sed.get(rid,{})
    has_move = len(o5)>=len(hl)*0.8 and len(o3)>=len(hl)*0.8
    entries = entry_cache.get(rid,{}); n = len(hl)
    idms = [entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm = np.mean(idms)
    riders = [entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider = np.mean(riders)
    ozd = oz_cache.get(rid,{}); mkt_d = odds_mkt
    oz_inv = {h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
    mk_inv = {h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
    oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1
    cyb_scores = [cyb_cache.get((rid,h),0) for h in hl]
    avg_cyb = np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0

    fps = result_full.get(rid, {})
    sorted_h = sorted(o3.items(), key=lambda x:x[1]) if o3 else []
    rank_map = {h:i+1 for i,(h,o) in enumerate(sorted_h)}

    # 馬ごと特徴量
    feats_h = {}
    for h in hl:
        feats_h[h] = build_horse_feat(h, entries, hl, avg_idm, avg_rider,
                                       oz_inv, oz_sum, mk_inv, mk_sum, avg_cyb,
                                       js, ts_st, hh, o5, o3, has_move, cyb_cache, rid)

    # --- 馬単 ---
    co_ut = {}
    for row in cdb.execute("SELECT combination,odds FROM confirmed_odds WHERE race_id=? AND bet_type='umatan' AND odds>0", (rid,)).fetchall():
        co_ut[row[0]] = row[1]
    if len(co_ut) >= 3:
        inv_ut = {k:1.0/v for k,v in co_ut.items()}; total_inv = sum(inv_ut.values())
        if total_inv > 0:
            mkt_prob_ut = {k:v/total_inv for k,v in inv_ut.items()}
            # 1着-2着（順序あり）
            top2 = sorted([r for r in result_cache.get(rid,[]) if r['fp'] in (1,2)], key=lambda x:x['fp'])
            if len(top2) >= 2:
                winner_combo = f"{top2[0]['hn']}-{top2[1]['hn']}"
                if year not in ds['umatan']:
                    ds['umatan'][year] = {'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
                for combo, odds_val in co_ut.items():
                    parts = combo.split('-')
                    if len(parts) != 2: continue
                    try: h1, h2 = int(parts[0]), int(parts[1])
                    except: continue
                    if h1 not in feats_h or h2 not in feats_h: continue
                    # 馬単: 順序あり → h1が1着、h2が2着
                    # 特徴量: 1着候補と2着候補を区別
                    pf = make_pair_features(feats_h[h1], feats_h[h2])
                    # 順序特徴量を追加
                    pf['first_odds'] = feats_h[h1].get('win_odds_3min',0)
                    pf['second_odds'] = feats_h[h2].get('win_odds_3min',0)
                    pf['first_move'] = feats_h[h1].get('move_5to3',0)
                    pf['second_move'] = feats_h[h2].get('move_5to3',0)
                    if FNAMES['umatan'] is None: FNAMES['umatan'] = sorted(pf.keys())
                    mp_val = mkt_prob_ut.get(combo, 1e-8)
                    init = math.log(max(mp_val, 1e-15)) - math.log(max(1-mp_val, 1e-15))
                    is_hit = 1 if combo == winner_combo else 0
                    pop_high = min(rank_map.get(h1,99), rank_map.get(h2,99))
                    ds['umatan'][year]['X'].append([pf.get(k,0) for k in FNAMES['umatan']])
                    ds['umatan'][year]['y'].append(is_hit)
                    ds['umatan'][year]['init'].append(init)
                    ds['umatan'][year]['meta'].append((rid, combo))
                    ds['umatan'][year]['odds'].append(odds_val)
                    ds['umatan'][year]['pop'].append(pop_high)

    # --- 三連複（上位8頭のC(8,3)=56組のみ、メモリ節約） ---
    co_tr = {}
    for row in cdb.execute("SELECT combination,odds FROM confirmed_odds WHERE race_id=? AND bet_type='sanrenpuku' AND odds>0", (rid,)).fetchall():
        co_tr[row[0]] = row[1]
    if len(co_tr) >= 3:
        # 上位8頭に絞る
        top8_hns = [h for h,_ in sorted(o3.items(), key=lambda x:x[1])[:8]] if o3 else hl[:8]
        inv_tr = {k:1.0/v for k,v in co_tr.items()}; total_inv = sum(inv_tr.values())
        if total_inv > 0:
            mkt_prob_tr = {k:v/total_inv for k,v in inv_tr.items()}
            top3 = sorted([r for r in result_cache.get(rid,[]) if r['fp'] in (1,2,3)], key=lambda x:x['fp'])
            if len(top3) >= 3:
                winner_combo = '-'.join(str(x) for x in sorted([top3[0]['hn'], top3[1]['hn'], top3[2]['hn']]))
                if year not in ds['trio']:
                    ds['trio'][year] = {'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}
                from itertools import combinations as comb3
                for a,b,c in comb3(top8_hns, 3):
                    combo = '-'.join(str(x) for x in sorted([a,b,c]))
                    if combo not in co_tr: continue
                    odds_val = co_tr[combo]
                    if a not in feats_h or b not in feats_h or c not in feats_h: continue
                    pf = make_trio_features(feats_h[a], feats_h[b], feats_h[c])
                    if FNAMES['trio'] is None: FNAMES['trio'] = sorted(pf.keys())
                    mp_val = mkt_prob_tr.get(combo, 1e-8)
                    init = math.log(max(mp_val, 1e-15)) - math.log(max(1-mp_val, 1e-15))
                    is_hit = 1 if combo == winner_combo else 0
                    pop_high = min(rank_map.get(a,99), rank_map.get(b,99), rank_map.get(c,99))
                    ds['trio'][year]['X'].append([pf.get(k,0) for k in FNAMES['trio']])
                    ds['trio'][year]['y'].append(is_hit)
                    ds['trio'][year]['init'].append(init)
                    ds['trio'][year]['meta'].append((rid, combo))
                    ds['trio'][year]['odds'].append(odds_val)
                    ds['trio'][year]['pop'].append(pop_high)
    do_update()
    n_proc += 1
    if n_proc % 2000 == 0: print(f"  {n_proc} races...", flush=True)
cdb.close()

for bt in ds:
    for y in sorted(ds[bt].keys()):
        d = ds[bt][y]; d['X'] = np.array(d['X'], dtype=np.float32); d['y'] = np.array(d['y'])
        d['init'] = np.array(d['init'], dtype=np.float64); d['odds'] = np.array(d['odds']); d['pop'] = np.array(d['pop'])
    sizes = ', '.join(str(y)+':'+str(len(ds[bt][y]['X'])) for y in sorted(ds[bt].keys()))
    print(f"  {bt}: {sizes}")

# === WF ===
lgb_params = {'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
              'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
              'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(bt_ds, fnames, bt_name, hjc_type):
    print(f"\n--- {bt_name} WF ---")
    all_bets = []
    for test_yr in [2024,2025,2026]:
        train_yrs = [y for y in range(2022, test_yr) if y in bt_ds]; fit_yr = test_yr-1
        if not train_yrs or fit_yr not in bt_ds or test_yr not in bt_ds: continue
        X_tr = np.vstack([bt_ds[y]['X'] for y in train_yrs])
        y_tr = np.concatenate([bt_ds[y]['y'] for y in train_yrs])
        init_tr = np.concatenate([bt_ds[y]['init'] for y in train_yrs])
        model = lgb.train(lgb_params, lgb.Dataset(X_tr, y_tr, feature_name=fnames, init_score=init_tr), num_boost_round=300)
        X_f = bt_ds[fit_yr]['X']; y_f = bt_ds[fit_yr]['y']; init_f = bt_ds[fit_yr]['init']
        raw_f = model.predict(X_f, raw_score=True)
        rd_f = defaultdict(list)
        for i,(rid,combo) in enumerate(bt_ds[fit_yr]['meta']): rd_f[rid].append(i)
        def neg_ll(p):
            b,tau = p; nll=0; nr=0
            for rid2,idxs in rd_f.items():
                ys=y_f[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        def neg_ll_mkt(init,y,rd):
            nll=0; nr=0
            for rid2,idxs in rd.items():
                ys=y[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=init[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res = minimize(neg_ll, x0=[1.0,1.0], method='Nelder-Mead', options={'maxiter':1000})
        b_use,tau_use = res.x
        X_te=bt_ds[test_yr]['X']; y_te=bt_ds[test_yr]['y']; init_te=bt_ds[test_yr]['init']
        meta_te=bt_ds[test_yr]['meta']; odds_te=bt_ds[test_yr]['odds']; pop_te=bt_ds[test_yr]['pop']
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,combo) in enumerate(meta_te): rd_te[rid].append(i)
        nll_mkt=neg_ll_mkt(init_te,y_te,rd_te)
        nll_mdl=0; nr_t=0
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            nll_mdl-=(s[wi[0]]-math.log(np.exp(s).sum())); nr_t+=1
        nll_mdl=nll_mdl/nr_t if nr_t>0 else 999
        delta=nll_mkt-nll_mdl
        print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f} delta={delta:+.5f}")
        # top5 features
        imp=model.feature_importance(importance_type='gain')
        top5=sorted(zip(fnames,imp),key=lambda x:-x[1])[:5]
        print(f"    top5: {[(f,f'{g:.0f}') for f,g in top5]}")
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; o=odds_te[idx]; ev=probs[j]*o
                is_hit=y_te[idx]
                payout=hjc_all.get(rid2,{}).get(hjc_type,{}).get(combo,0) if is_hit else 0
                all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'pop':int(pop_te[idx]),'rid':rid2})
    return all_bets

bets_umatan = run_wf(ds['umatan'], FNAMES['umatan'], '馬単', 'umatan_hjc')
bets_trio = run_wf(ds['trio'], FNAMES['trio'], '三連複', 'sanrenpuku_hjc')

# === 結果 ===
print(f"\n{'='*90}")
print("v20g: 三連複・馬単 プール直接基準 + move_5to3")
print(f"{'='*90}")

for bt_label, data in [('馬単', bets_umatan), ('三連複', bets_trio)]:
    print(f"\n  {bt_label}:")
    print(f"  {'フィルタ':>14} {'EV>=':>5} {'n':>7} {'的中':>5} {'的中率':>6} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
    print(f"  {'-'*80}")
    for pop_label, pop_max in [('1番人気含む',1),('1-3番人気含む',3),('全組合せ',99)]:
        for ev_th in [1.0, 1.2, 1.3, 1.5]:
            sub = [d for d in data if d['ev']>=ev_th and d['pop']<=pop_max]
            if not sub or len(sub)<10: continue
            n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n if n else 0
            inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100 if inv>0 else 0
            parts=[]
            for yr in [2024,2025,2026]:
                ys=[d for d in sub if d['year']==yr]
                if not ys: parts.append(''); continue
                yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
                parts.append(f"{yp/yi*100:.1f}%")
            print(f"  {pop_label:>14} {ev_th:>4.1f} {n:>7} {hits:>5} {hr:>5.2%} {rec:>6.1f}% | {' '.join(parts)}")

# ブートストラップCI（主要パターン）
print(f"\n--- ブートストラップCI ---")
for bt_label, data in [('馬単', bets_umatan), ('三連複', bets_trio)]:
    for pop_label, pop_max in [('1番人気含む',1),('全組合せ',99)]:
        for ev_th in [1.0, 1.2]:
            sub = [d for d in data if d['ev']>=ev_th and d['pop']<=pop_max]
            if len(sub)<100: continue
            by_race=defaultdict(list)
            for d in sub: by_race[d['rid']].append(d)
            rids=list(by_race.keys())
            np.random.seed(42); br=[]
            for _ in range(5000):
                samp=np.random.choice(rids,size=len(rids),replace=True)
                si=0; sp=0
                for r in samp:
                    for d in by_race[r]: si+=100; sp+=d['payout']*100 if d['is_hit'] else 0
                if si>0: br.append(sp/si*100)
            br.sort()
            inv=len(sub)*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
            print(f"  {bt_label} {pop_label} EV>={ev_th}: n={len(sub):,} rec={pay/inv*100:.1f}% CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

# 全券種比較（v20馬連含む）
print(f"\n{'='*90}")
print("全券種比較（1番人気含む × EV>=1.2）")
print(f"{'='*90}")
print("  馬連(v20):  n=9,860  rec=108.7%  CI=[91.9%, 128.4%]  ← 既出")
for bt_label, data in [('馬単', bets_umatan), ('三連複', bets_trio)]:
    sub=[d for d in data if d['ev']>=1.2 and d['pop']<=1]
    if len(sub)<10: print(f"  {bt_label}: n={len(sub)} (不足)"); continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub)
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
    print(f"  {bt_label}:    n={n:,}  rec={rec:.1f}%")

print("\nDone!")
