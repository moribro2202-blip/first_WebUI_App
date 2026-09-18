# -*- coding: utf-8 -*-
"""v18: KAB(トラックバイアス) + TYB(調教) + CYB(気配) の特徴量審査
Phase 3基準: 現行24特徴量モデルに1つずつ追加してΔ_τを測定
"""
import sqlite3, math, sys, os, glob, re, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'

# ============================================================
# 1. KAB解析（トラックバイアス）- 固定幅バイトパース
# ============================================================
print("Parsing KAB (track bias)...", flush=True)
kab_data = {}  # (date_str, venue_code) -> {turf: {...}, dirt: {...}}

for fpath in sorted(glob.glob(os.path.join(JRDB, 'KAB', '*.txt'))):
    fname = os.path.basename(fpath)
    yy = fname[3:5]; mm = fname[5:7]; dd = fname[7:9]
    file_date = f"20{yy}-{mm}-{dd}"

    with open(fpath, 'rb') as f:
        for line in f.readlines():
            data = line.rstrip(b'\r\n')
            if len(data) < 70: continue
            venue = data[0:2].decode('ascii', 'replace')
            ap = data[21:].decode('ascii', 'replace')

            # 芝の情報
            try:
                turf_cond = int(ap[0:1]) if ap[0:1].strip() else 0
            except: turf_cond = 0
            try:
                dirt_cond = int(ap[1:2]) if ap[1:2].strip() else 0
            except: dirt_cond = 0

            # 芝コーナーバイアス（3桁: 各コーナー 1=内,2=フラット,3=外,4=大外）
            turf_bias_str = ap[3:6].strip()
            turf_bias = 2.0  # default flat
            if len(turf_bias_str) == 3 and turf_bias_str.isdigit():
                c1, c2, c3 = int(turf_bias_str[0]), int(turf_bias_str[1]), int(turf_bias_str[2])
                turf_bias = (c1 + c2 + c3) / 3.0

            # 芝馬場差（3文字, 右詰め, 符号あり）
            turf_diff_raw = ap[6:9].strip()
            try: turf_diff = int(turf_diff_raw)
            except: turf_diff = 0

            # 芝荒れ度（4コーナー, 各2文字）
            dmg_total = 0
            for pos in [9, 11, 13, 15]:
                try: dmg_total += max(0, int(ap[pos:pos+2].strip()))
                except: pass

            # ダートの情報（rest部分から）
            rest = ap[17:]
            # ダートバイアス: '222' 等、rest中の3桁を探す
            dirt_bias = 2.0
            dirt_diff = 0
            m = re.search(r'(\d{3})([-\d ]+)', rest)
            if m:
                db_str = m.group(1)
                if len(db_str) == 3:
                    dc1, dc2, dc3 = int(db_str[0]), int(db_str[1]), int(db_str[2])
                    dirt_bias = (dc1 + dc2 + dc3) / 3.0
                dd_str = m.group(2).strip().split()[0] if m.group(2).strip() else '0'
                try: dirt_diff = int(dd_str)
                except: dirt_diff = 0

            # 含水率（末尾の数値）
            moisture = 0
            m2 = re.search(r'(\d+\.\d+)\s*$', rest)
            if m2:
                try: moisture = float(m2.group(1))
                except: pass

            key = (file_date, venue)
            if key not in kab_data:
                kab_data[key] = {}
            kab_data[key]['turf'] = {
                'cond': turf_cond, 'bias': turf_bias, 'diff': turf_diff,
                'damage': dmg_total, 'moisture': moisture,
            }
            kab_data[key]['dirt'] = {
                'cond': dirt_cond, 'bias': dirt_bias, 'diff': dirt_diff,
            }

print(f"  KAB entries: {len(kab_data)}")
for k in sorted(kab_data.keys())[-3:]:
    print(f"  {k}: {kab_data[k]}")

# ============================================================
# 2. TYB解析（調教）
# ============================================================
print("\nParsing TYB (training)...", flush=True)
tyb_data = {}  # (date_str, venue_code, horse_number) -> train_total

for fpath in sorted(glob.glob(os.path.join(JRDB, 'TYB', '*.txt'))):
    fname = os.path.basename(fpath)
    yy = fname[3:5]; mm = fname[5:7]; dd = fname[7:9]
    file_date = f"20{yy}-{mm}-{dd}"
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 50: continue
            try:
                venue = line[0:2].decode('ascii')
                hn = int(line[8:10].decode('ascii').strip())
                total_time = float(line[40:45].decode('ascii').strip())
            except:
                continue
            tyb_data[(file_date, venue, hn)] = total_time

print(f"  TYB entries: {len(tyb_data)}")

# ============================================================
# 3. CYB気配コード
# ============================================================
print("\nParsing CYB (paddock demeanor)...", flush=True)
cyb_kehai = {}

for fpath in sorted(glob.glob(os.path.join(JRDB, 'CYB', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 38: continue
            raw = line.decode('ascii', 'replace')
            try:
                rid2 = f'{raw[2:4]}{raw[0:2]}{raw[4:6]}{raw[6:8]}'
                hn = int(raw[8:10])
                kehai = raw[35] if len(raw) > 35 else 'B'
            except:
                continue
            kehai_score = {'A': 2, 'B': 1, 'C': 0, 'D': -1}.get(kehai, 1)
            cyb_kehai[(rid2, hn)] = kehai_score

print(f"  CYB kehai entries: {len(cyb_kehai)}")
from collections import Counter
print(f"  Distribution: {dict(sorted(Counter(cyb_kehai.values()).items()))}")

# ============================================================
# 4. DB読み込み
# ============================================================
print("\nLoading DB...", flush=True)
db = sqlite3.connect(DB, timeout=30)
races_raw = db.execute('SELECT race_id,race_date,venue_code,surface,distance FROM races ORDER BY race_date,race_id').fetchall()
entry_cache = {}
for rid,_,_,_,_ in races_raw:
    es = db.execute('SELECT horse_number,horse_id,jockey_name,trainer_name,idm,total_index,rider_index,run_style,carried_weight FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid] = {e[0]:{'hid':e[1],'jockey':e[2],'trainer':e[3],'idm':e[4],'total':e[5],'rider':e[6],'run_style':e[7],'weight':e[8]} for e in es}
result_cache = defaultdict(list)
for row in db.execute('SELECT race_id,horse_number,finish_position,horse_id FROM results WHERE finish_position IS NOT NULL').fetchall():
    result_cache[row[0]].append({'hn':row[1],'fp':row[2],'hid':row[3]})
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
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

# race_idからKABを引くためのマップ
rid_to_info = {r[0]: {'date':r[1],'venue':r[2],'surface':r[3],'distance':r[4]} for r in races_raw}

# 候補特徴量
CANDIDATE_FEATURES = [
    'track_diff',       # 馬場差
    'inner_bias',       # コーナーバイアス
    'track_damage',     # 荒れ度
    'moisture',         # 含水率
    'bias_x_gate',      # inner_bias × gate_ratio
    'bias_x_senkou',    # (3-inner_bias) × is_senkou
    'diff_x_senkou',    # track_diff × is_senkou（速い馬場で先行有利）
    'train_total',      # 調教スコア
    'train_c',          # 調教スコア（レース平均との差）
    'cyb_kehai',        # 気配コード
]

# ============================================================
# データセット構築
# ============================================================
print("\nBuilding datasets...", flush=True)
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
        datasets[year]={'X':[],'y':[],'init':[],'meta':[],'extras':[]}
    hl=race_horses.get(rid,[])
    if len(hl)>=5:
        rl=result_cache.get(rid,[])
        if rl:
            winners=[r['hn'] for r in rl if r['fp']==1]
            if winners and winners[0] in hl:
                odds_mkt=ts3.get(rid,{})
                if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
                inv_arr=np.array([1/odds_mkt.get(h,999) for h in hl])
                s=inv_arr.sum()
                if s==0: do_update(); continue
                mp=inv_arr/s; mp=mp**1.015; mp/=mp.sum()
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

                # KAB
                kab = kab_data.get((rd, vc), {})
                sf_key = 'turf' if sf in ('芝',) else 'dirt'
                kab_sf = kab.get(sf_key, {})
                track_diff = kab_sf.get('diff', 0)
                inner_bias = kab_sf.get('bias', 2.0)
                track_damage = kab_sf.get('damage', 0)
                moisture = kab_sf.get('moisture', 0)

                # TYB（レースレベル）
                train_scores = []
                for h in hl:
                    t = tyb_data.get((rd, vc, h), 0)
                    train_scores.append(t)
                avg_train = np.mean(train_scores) if any(t > 0 for t in train_scores) else 0

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
                    is_senkou = 1 if ent.get('run_style','') in ('逃げ','先行') else 0
                    f['is_senkou']=is_senkou
                    gate_ratio = h/n
                    f['gate_ratio']=gate_ratio
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
                    p_val=mp[i]
                    datasets[year]['init'].append(math.log(max(p_val,1e-15))-math.log(max(1-p_val,1e-15)))
                    datasets[year]['meta'].append((rid,h))

                    # 候補特徴量
                    t_score = train_scores[i]
                    extras = {
                        'track_diff': track_diff,
                        'inner_bias': inner_bias,
                        'track_damage': track_damage,
                        'moisture': moisture,
                        'bias_x_gate': (inner_bias - 2.0) * gate_ratio,
                        'bias_x_senkou': (3.0 - inner_bias) * is_senkou,
                        'diff_x_senkou': track_diff * is_senkou,
                        'train_total': t_score,
                        'train_c': (t_score - avg_train) if avg_train > 0 else 0,
                        'cyb_kehai': cyb_kehai.get((rid, h), 1),
                    }
                    datasets[year]['extras'].append([extras.get(k, 0) for k in CANDIDATE_FEATURES])
    do_update()

for y in sorted(datasets.keys()):
    d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64)
    d['extras']=np.array(d['extras'],dtype=np.float32)
    print(f"  {y}: {len(d['X']):,}")

# カバレッジ確認
print(f"\n--- 候補特徴量のカバレッジ ---")
for i, name in enumerate(CANDIDATE_FEATURES):
    all_vals = np.concatenate([d['extras'][:, i] for d in datasets.values()])
    non_zero = np.count_nonzero(all_vals)
    non_default = np.sum(all_vals != (2.0 if name == 'inner_bias' else 0))
    print(f"  {name:20s}: non-zero={non_zero:,}/{len(all_vals):,} ({non_zero/len(all_vals):.1%}) "
          f"mean={np.mean(all_vals):.3f} std={np.std(all_vals):.3f} "
          f"min={np.min(all_vals):.1f} max={np.max(all_vals):.1f}")

# ============================================================
# Δ_τテスト
# ============================================================
lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(datasets, fnames):
    results = []
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in datasets]
        fit_yr=test_yr-1
        if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
        X_tr=np.vstack([datasets[y]['X_aug'] for y in train_yrs])
        y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
        dtrain=lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr)
        model=lgb.train(lgb_params,dtrain,num_boost_round=300)
        X_f=datasets[fit_yr]['X_aug']; y_f=datasets[fit_yr]['y']; init_f=datasets[fit_yr]['init']
        meta_f=datasets[fit_yr]['meta']; raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_f): rd_f[rid].append(i)
        def neg_ll_base(init, y, rd):
            nll=0; nr=0
            for rid2,idxs in rd.items():
                ys2=y[idxs]; wi=np.where(ys2==1)[0]
                if len(wi)==0: continue
                s=init[idxs]; s=s-s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        def neg_ll(p, init, raw, y, rd):
            b,tau=p; nll=0; nr=0
            for rid2,idxs in rd.items():
                ys2=y[idxs]; wi=np.where(ys2==1)[0]
                if len(wi)==0: continue
                s=b*init[idxs]+tau*raw[idxs]; s=s-s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res_opt=minimize(lambda p: neg_ll(p, init_f, raw_f, y_f, rd_f),
                         x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        b_use,tau_use=res_opt.x
        X_te=datasets[test_yr]['X_aug']; y_te=datasets[test_yr]['y']
        init_te=datasets[test_yr]['init']; meta_te=datasets[test_yr]['meta']
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,hn) in enumerate(meta_te): rd_te[rid].append(i)
        nll_mkt = neg_ll_base(init_te, y_te, rd_te)
        nll_mdl = neg_ll([b_use,tau_use], init_te, raw_te, y_te, rd_te)
        delta = nll_mkt - nll_mdl
        results.append({'year':test_yr,'b':b_use,'tau':tau_use,'delta':delta})
    return results

# ベースライン
print(f"\n{'='*80}")
print("ベースライン（24特徴量）")
print(f"{'='*80}")
for y in datasets: datasets[y]['X_aug'] = datasets[y]['X']
base_results = run_wf(datasets, FNAMES)
base_deltas = [r['delta'] for r in base_results]
for r in base_results:
    print(f"  {r['year']}: b={r['b']:.3f} tau={r['tau']:.3f} Δ_τ={r['delta']:+.5f}")

# 各候補テスト
print(f"\n{'='*80}")
print("候補特徴量の個別テスト（24+1）")
print(f"{'='*80}")

results_summary = []
for feat_idx, feat_name in enumerate(CANDIDATE_FEATURES):
    for y in datasets:
        extra_col = datasets[y]['extras'][:, feat_idx:feat_idx+1]
        datasets[y]['X_aug'] = np.hstack([datasets[y]['X'], extra_col])
    aug_fnames = FNAMES + [feat_name]
    feat_results = run_wf(datasets, aug_fnames)
    deltas = [r['delta'] for r in feat_results]
    improvements = [d - bd for d, bd in zip(deltas, base_deltas)]
    yr_plus = sum(1 for imp in improvements if imp > 0)
    avg_imp = np.mean(improvements)
    results_summary.append({'name': feat_name, 'yr_plus': yr_plus, 'avg_imp': avg_imp, 'improvements': improvements})

# サマリー
print(f"\n{'='*80}")
print("サマリー")
print(f"{'='*80}")
print(f"  {'特徴量':20s} {'年+':>4} {'平均改善':>10} {'2024':>8} {'2025':>8} {'2026':>8} {'判定':>8}")
print(f"  {'-'*72}")
for r in sorted(results_summary, key=lambda x: -x['avg_imp']):
    imps = r['improvements']
    judgment = 'PASS' if r['yr_plus'] >= 3 else ('候補' if r['yr_plus'] >= 2 else 'FAIL')
    print(f"  {r['name']:20s} {r['yr_plus']:>3}/3 {r['avg_imp']:>+9.6f} "
          f"{imps[0]:>+7.5f} {imps[1]:>+7.5f} {imps[2]:>+7.5f} {judgment:>8}")

print("\nDone!")
