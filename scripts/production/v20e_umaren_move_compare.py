# -*- coding: utf-8 -*-
"""v20e: 馬連 move_5to3 vs move_5to2 vs move_5to1 比較
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
# 全時点のオッズ
ts_all = {}
for mins in [1,2,3,5]:
    ts_all[mins] = defaultdict(dict)
    for rid,hn,odds in db.execute('SELECT race_id,horse_number,odds FROM ts_win_odds WHERE minutes_before=? AND odds>0',(mins,)).fetchall():
        ts_all[mins][rid][hn] = odds
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

# move variants: (name, early_min, late_min)
MOVE_VARIANTS = [
    ('move_5to1', 5, 1),
    ('move_5to2', 5, 2),
    ('move_5to3', 5, 3),
]

for move_name, early_min, late_min in MOVE_VARIANTS:
    print(f"\n{'='*80}")
    print(f"  {move_name} (発走{early_min}分前 → {late_min}分前)")
    print(f"{'='*80}")

    o_early = ts_all[early_min]
    o_late = ts_all[late_min]

    # ペアデータセット構築
    js={}; hh={}; ts_st={}; pair_ds={}; PFNAMES=None
    cdb = sqlite3.connect(DB, timeout=30)

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

        # 市場オッズ: late_minを使う
        odds_mkt = o_late.get(rid, {})
        if len(odds_mkt) < len(hl)*0.8: odds_mkt = sed.get(rid, {})
        oe = o_early.get(rid, {}); ol = o_late.get(rid, {})
        has_move = len(oe) >= len(hl)*0.8 and len(ol) >= len(hl)*0.8
        entries = entry_cache.get(rid, {}); n = len(hl)
        idms = [entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm = np.mean(idms)
        riders = [entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider = np.mean(riders)
        ozd = oz_cache.get(rid, {}); mkt_d = odds_mkt
        oz_inv = {h:1/ozd[h] if h in ozd and ozd[h]>0 else 0 for h in hl}
        mk_inv = {h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
        oz_sum = sum(oz_inv.values()) or 1; mk_sum = sum(mk_inv.values()) or 1
        cyb_scores = [cyb_cache.get((rid,h),0) for h in hl]
        avg_cyb = np.mean(cyb_scores) if any(c!=0 for c in cyb_scores) else 0

        co = {}
        for row in cdb.execute("SELECT combination,odds FROM confirmed_odds WHERE race_id=? AND bet_type='umaren' AND odds>0", (rid,)).fetchall():
            co[row[0]] = row[1]
        if len(co) < 3: do_update(); continue
        inv_um = {k:1.0/v for k,v in co.items()}; total_inv = sum(inv_um.values())
        if total_inv == 0: do_update(); continue
        mkt_prob = {k:v/total_inv for k,v in inv_um.items()}
        top2 = sorted([r for r in result_cache.get(rid,[]) if r['fp'] in (1,2)], key=lambda x:x['fp'])
        if len(top2) < 2: do_update(); continue
        winner_combo = '-'.join(str(x) for x in sorted([top2[0]['hn'], top2[1]['hn']]))

        sorted_h = sorted(ol.items(), key=lambda x:x[1]) if ol else []
        rank_map = {h:i+1 for i,(h,o) in enumerate(sorted_h)}

        if year not in pair_ds:
            pair_ds[year] = {'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}

        feats_h = {}
        for h in hl:
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
                v_e = oe.get(h,0); v_l = ol.get(h,0)
                f['move'] = (v_e - v_l) / v_e if v_e > 0 and v_l > 0 else 0
            else:
                f['move'] = 0
            f['win_odds'] = ol.get(h, 0)
            feats_h[h] = f

        for combo, odds_val in co.items():
            parts = combo.split('-')
            if len(parts) != 2: continue
            try: h1, h2 = int(parts[0]), int(parts[1])
            except: continue
            if h1 not in feats_h or h2 not in feats_h: continue
            f1 = feats_h[h1]; f2 = feats_h[h2]
            pf = {}
            for key in ['idm_c','rider_c','total_index','expert_resid','cyb_c',
                         'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
                         'top3_rate','last_fp','win_rate','is_senkou','move']:
                v1 = f1.get(key,0); v2 = f2.get(key,0)
                pf[f'{key}_sum'] = v1 + v2
                pf[f'{key}_diff'] = abs(v1 - v2)
            ow1 = f1.get('win_odds',0); ow2 = f2.get('win_odds',0)
            pf['win_odds_ratio'] = min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
            pf['win_odds_sum_inv'] = (1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
            if PFNAMES is None: PFNAMES = sorted(pf.keys())
            mp_val = mkt_prob.get(combo, 1e-8)
            init = math.log(max(mp_val, 1e-15)) - math.log(max(1-mp_val, 1e-15))
            is_hit = 1 if combo == winner_combo else 0
            pop_high = min(rank_map.get(h1,99), rank_map.get(h2,99))
            pair_ds[year]['X'].append([pf.get(k,0) for k in PFNAMES])
            pair_ds[year]['y'].append(is_hit)
            pair_ds[year]['init'].append(init)
            pair_ds[year]['meta'].append((rid, combo))
            pair_ds[year]['odds'].append(odds_val)
            pair_ds[year]['pop'].append(pop_high)
        do_update()
    cdb.close()

    for y in sorted(pair_ds.keys()):
        d = pair_ds[y]; d['X'] = np.array(d['X'], dtype=np.float32); d['y'] = np.array(d['y'])
        d['init'] = np.array(d['init'], dtype=np.float64); d['odds'] = np.array(d['odds']); d['pop'] = np.array(d['pop'])

    # WF
    lgb_params = {'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
                  'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
                  'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
    all_bets = []
    for test_yr in [2024,2025,2026]:
        train_yrs = [y for y in range(2022, test_yr) if y in pair_ds]; fit_yr = test_yr - 1
        if not train_yrs or fit_yr not in pair_ds or test_yr not in pair_ds: continue
        X_tr = np.vstack([pair_ds[y]['X'] for y in train_yrs])
        y_tr = np.concatenate([pair_ds[y]['y'] for y in train_yrs])
        init_tr = np.concatenate([pair_ds[y]['init'] for y in train_yrs])
        model = lgb.train(lgb_params, lgb.Dataset(X_tr, y_tr, feature_name=PFNAMES, init_score=init_tr), num_boost_round=300)
        X_f = pair_ds[fit_yr]['X']; y_f = pair_ds[fit_yr]['y']; init_f = pair_ds[fit_yr]['init']
        raw_f = model.predict(X_f, raw_score=True)
        rd_f = defaultdict(list)
        for i, (rid, combo) in enumerate(pair_ds[fit_yr]['meta']): rd_f[rid].append(i)
        def neg_ll(p):
            b, tau = p; nll = 0; nr = 0
            for rid2, idxs in rd_f.items():
                ys = y_f[idxs]; wi = np.where(ys==1)[0]
                if len(wi)==0: continue
                s = b*init_f[idxs]+tau*raw_f[idxs]; s -= s.max()
                nll -= (s[wi[0]]-math.log(np.exp(s).sum())); nr += 1
            return nll/nr if nr > 0 else 999
        def neg_ll_mkt(init, y, rd):
            nll = 0; nr = 0
            for rid2, idxs in rd.items():
                ys = y[idxs]; wi = np.where(ys==1)[0]
                if len(wi)==0: continue
                s = init[idxs]; s -= s.max()
                nll -= (s[wi[0]]-math.log(np.exp(s).sum())); nr += 1
            return nll/nr if nr > 0 else 999
        res = minimize(neg_ll, x0=[1.0,1.0], method='Nelder-Mead', options={'maxiter':1000})
        b_use, tau_use = res.x
        X_te = pair_ds[test_yr]['X']; y_te = pair_ds[test_yr]['y']
        init_te = pair_ds[test_yr]['init']; meta_te = pair_ds[test_yr]['meta']
        odds_te = pair_ds[test_yr]['odds']; pop_te = pair_ds[test_yr]['pop']
        raw_te = model.predict(X_te, raw_score=True)
        rd_te = defaultdict(list)
        for i, (rid, combo) in enumerate(meta_te): rd_te[rid].append(i)
        nll_mkt = neg_ll_mkt(init_te, y_te, rd_te)
        nll_mdl = 0; nr_t = 0
        for rid2, idxs in rd_te.items():
            ys = y_te[idxs]; wi = np.where(ys==1)[0]
            if len(wi)==0: continue
            s = b_use*init_te[idxs]+tau_use*raw_te[idxs]; s -= s.max()
            nll_mdl -= (s[wi[0]]-math.log(np.exp(s).sum())); nr_t += 1
        nll_mdl = nll_mdl/nr_t if nr_t > 0 else 999
        delta = nll_mkt - nll_mdl
        print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f} delta={delta:+.5f}")
        for rid2, idxs in rd_te.items():
            ys = y_te[idxs]; wi = np.where(ys==1)[0]
            if len(wi)==0: continue
            s = b_use*init_te[idxs]+tau_use*raw_te[idxs]; s -= s.max()
            probs = np.exp(s)/np.exp(s).sum()
            for j, idx in enumerate(idxs):
                combo = meta_te[idx][1]; o = odds_te[idx]; ev = probs[j]*o
                is_hit = y_te[idx]
                payout = hjc_all.get(rid2,{}).get('umaren_hjc',{}).get(combo,0) if is_hit else 0
                all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'pop':int(pop_te[idx]),'rid':rid2})

    # 結果
    for pop_label, pop_max in [('1番人気含む',1),('全組合せ',99)]:
        for ev_th in [1.0, 1.2, 1.3]:
            sub = [d for d in all_bets if d['ev']>=ev_th and d['pop']<=pop_max]
            if not sub or len(sub)<10: continue
            n=len(sub); hits=sum(d['is_hit'] for d in sub)
            inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
            parts=[]
            for yr in [2024,2025,2026]:
                ys=[d for d in sub if d['year']==yr]
                if not ys: parts.append(''); continue
                yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
                parts.append(f"{yp/yi*100:.1f}%")
            print(f"  {pop_label:>14} EV>={ev_th}: n={n:,} rec={rec:.1f}% | {' '.join(parts)}")

    # PFNAMES リセット（次のmove variantで再構築）
    PFNAMES = None

print("\nDone!")
