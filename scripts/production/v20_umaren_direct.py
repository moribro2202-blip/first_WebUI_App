# -*- coding: utf-8 -*-
"""v20: 馬連プール直接基準モデル
馬連confirmed_oddsから市場確率を算出し、
ペアレベルの特徴量（2頭の残差の和/差など）で残差モデルを構築。
SH変換を通さない。

構造:
  市場確率: π_ij = (1/odds_ij) / Σ(1/odds_kl)  ← 馬連プールから直接
  残差: r_ij = f(horse_i_features, horse_j_features)
  強さ: s_ij = b × ln(π_ij) + τ × r_ij
  確率: P(ij wins) = exp(s_ij) / Σ exp(s_kl)
  EV: P(ij) × odds_ij
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

# ==================================================================
# 馬ごとの特徴量を構築（単勝モデルと同じ）→ ペアに変換
# ==================================================================
print("Building horse-level features...", flush=True)
js={}; hh={}; ts_st={}
# race_id -> {horse_number -> feature_dict}
horse_features = {}

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

    odds_mkt=ts3.get(rid,{})
    if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
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

    race_feats = {}
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
        # 単勝3分前オッズ
        f['win_odds_3min'] = o3.get(h, 0)
        race_feats[h] = f
    horse_features[rid] = race_feats
    do_update()

print(f"  Races with features: {len(horse_features)}")

# ==================================================================
# ペアレベル特徴量の構築 + 馬連WFテスト
# ==================================================================
print("\nBuilding pair datasets...", flush=True)

PAIR_FNAMES = None
pair_datasets = {}  # year -> {X, y, init, meta, odds}

cdb = sqlite3.connect(DB, timeout=30)
for rid, rd, vc, sf, dt in races_raw:
    year = int(rd[:4])
    if year < 2022: continue
    if rid not in horse_features: continue
    feats = horse_features[rid]
    hl = race_horses.get(rid, [])
    fps = result_full.get(rid, {})

    # 馬連confirmed_odds
    co_um = {}
    for row in cdb.execute("SELECT combination,odds FROM confirmed_odds WHERE race_id=? AND bet_type='umaren' AND odds>0", (rid,)).fetchall():
        co_um[row[0]] = row[1]
    if len(co_um) < 3: continue

    # 市場確率
    inv_um = {k: 1.0/v for k,v in co_um.items()}
    total_inv = sum(inv_um.values())
    if total_inv == 0: continue
    mkt_prob = {k: v/total_inv for k,v in inv_um.items()}

    # 1-2着の組合せ
    top2 = sorted([r for r in result_cache.get(rid,[]) if r['fp'] in (1,2)], key=lambda x:x['fp'])
    if len(top2) < 2: continue
    winner_combo = '-'.join(str(x) for x in sorted([top2[0]['hn'], top2[1]['hn']]))

    if year not in pair_datasets:
        pair_datasets[year] = {'X':[],'y':[],'init':[],'meta':[],'odds':[]}

    # 全組合せ（confirmed_oddsにある組合せのみ）
    for combo, odds in co_um.items():
        parts = combo.split('-')
        if len(parts) != 2: continue
        try:
            h1, h2 = int(parts[0]), int(parts[1])
        except: continue
        if h1 not in feats or h2 not in feats: continue

        f1 = feats[h1]; f2 = feats[h2]
        # ペア特徴量: 2頭の特徴量の和・差・積
        pf = {}
        for key in ['idm_c','rider_c','total_index','expert_resid','cyb_c',
                     'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
                     'top3_rate','last_fp','win_rate','is_senkou','move_5to3']:
            v1 = f1.get(key, 0); v2 = f2.get(key, 0)
            pf[f'{key}_sum'] = v1 + v2
            pf[f'{key}_diff'] = abs(v1 - v2)  # 対称性のためabs
        # 単勝オッズの比率
        o1 = f1.get('win_odds_3min', 0); o2 = f2.get('win_odds_3min', 0)
        pf['win_odds_ratio'] = min(o1,o2)/max(o1,o2) if o1>0 and o2>0 else 0
        pf['win_odds_sum_inv'] = (1/o1+1/o2) if o1>0 and o2>0 else 0

        if PAIR_FNAMES is None:
            PAIR_FNAMES = sorted(pf.keys())

        mp = mkt_prob.get(combo, 1e-8)
        init = math.log(max(mp, 1e-15)) - math.log(max(1-mp, 1e-15))
        is_hit = 1 if combo == winner_combo else 0

        pair_datasets[year]['X'].append([pf.get(k,0) for k in PAIR_FNAMES])
        pair_datasets[year]['y'].append(is_hit)
        pair_datasets[year]['init'].append(init)
        pair_datasets[year]['meta'].append((rid, combo))
        pair_datasets[year]['odds'].append(odds)

cdb.close()

for y in sorted(pair_datasets.keys()):
    d = pair_datasets[y]
    d['X'] = np.array(d['X'], dtype=np.float32)
    d['y'] = np.array(d['y'])
    d['init'] = np.array(d['init'], dtype=np.float64)
    d['odds'] = np.array(d['odds'])
    n_races = len(set(m[0] for m in d['meta']))
    print(f"  {y}: {len(d['X']):,} pairs ({n_races} races)")

# ==================================================================
# WFテスト
# ==================================================================
lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

print("\nRunning WF...", flush=True)
all_bets = []

for test_yr in [2024,2025,2026]:
    train_yrs = [y for y in range(2022, test_yr) if y in pair_datasets]
    fit_yr = test_yr - 1
    if not train_yrs or fit_yr not in pair_datasets or test_yr not in pair_datasets: continue

    X_tr = np.vstack([pair_datasets[y]['X'] for y in train_yrs])
    y_tr = np.concatenate([pair_datasets[y]['y'] for y in train_yrs])
    init_tr = np.concatenate([pair_datasets[y]['init'] for y in train_yrs])
    dtrain = lgb.Dataset(X_tr, y_tr, feature_name=PAIR_FNAMES, init_score=init_tr)
    model = lgb.train(lgb_params, dtrain, num_boost_round=300)

    # フィット年でb,τ
    X_f = pair_datasets[fit_yr]['X']; y_f = pair_datasets[fit_yr]['y']
    init_f = pair_datasets[fit_yr]['init']; meta_f = pair_datasets[fit_yr]['meta']
    raw_f = model.predict(X_f, raw_score=True)
    rd_f = defaultdict(list)
    for i, (rid, combo) in enumerate(meta_f): rd_f[rid].append(i)

    def neg_ll(p):
        b,tau = p; nll = 0; nr = 0
        for rid2, idxs in rd_f.items():
            ys = y_f[idxs]; wi = np.where(ys==1)[0]
            if len(wi) == 0: continue
            s = b*init_f[idxs] + tau*raw_f[idxs]; s -= s.max()
            nll -= (s[wi[0]] - math.log(np.exp(s).sum())); nr += 1
        return nll/nr if nr > 0 else 999

    # 市場のみの対数尤度
    def neg_ll_mkt(init, y, rd):
        nll = 0; nr = 0
        for rid2, idxs in rd.items():
            ys = y[idxs]; wi = np.where(ys==1)[0]
            if len(wi) == 0: continue
            s = init[idxs]; s -= s.max()
            nll -= (s[wi[0]] - math.log(np.exp(s).sum())); nr += 1
        return nll/nr if nr > 0 else 999

    res = minimize(neg_ll, x0=[1.0, 1.0], method='Nelder-Mead', options={'maxiter':1000})
    b_use, tau_use = res.x

    # テスト年
    X_te = pair_datasets[test_yr]['X']; y_te = pair_datasets[test_yr]['y']
    init_te = pair_datasets[test_yr]['init']; meta_te = pair_datasets[test_yr]['meta']
    odds_te = pair_datasets[test_yr]['odds']
    raw_te = model.predict(X_te, raw_score=True)
    rd_te = defaultdict(list)
    for i, (rid, combo) in enumerate(meta_te): rd_te[rid].append(i)

    nll_mkt = neg_ll_mkt(init_te, y_te, rd_te)
    nll_mdl_val = 0; nr = 0
    for rid2, idxs in rd_te.items():
        ys = y_te[idxs]; wi = np.where(ys==1)[0]
        if len(wi) == 0: continue
        s = b_use*init_te[idxs] + tau_use*raw_te[idxs]; s -= s.max()
        nll_mdl_val -= (s[wi[0]] - math.log(np.exp(s).sum())); nr += 1
    nll_mdl = nll_mdl_val/nr if nr > 0 else 999
    delta = nll_mkt - nll_mdl

    print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f} delta={delta:+.5f}")

    # EV計算（レース単位で正規化）
    for rid2, idxs in rd_te.items():
        ys = y_te[idxs]; wi = np.where(ys==1)[0]
        if len(wi) == 0: continue
        s = b_use*init_te[idxs] + tau_use*raw_te[idxs]; s -= s.max()
        probs = np.exp(s) / np.exp(s).sum()
        for j, idx in enumerate(idxs):
            combo = meta_te[idx][1]
            o = odds_te[idx]
            ev = probs[j] * o
            is_hit = y_te[idx]
            payout = hjc_all.get(rid2,{}).get('umaren_hjc',{}).get(combo,0) if is_hit else 0
            all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                             'payout':payout,'odds':o,'rid':rid2,'combo':combo,
                             'mdl_p':float(probs[j])})

    # 特徴量重要度
    imp = model.feature_importance(importance_type='gain')
    top_feats = sorted(zip(PAIR_FNAMES, imp), key=lambda x:-x[1])[:10]
    print(f"    Top features: {[(f,f'{g:.0f}') for f,g in top_feats]}")

# === 結果 ===
print(f"\n{'='*85}")
print("v20: 馬連プール直接基準モデル")
print(f"{'='*85}")
print(f"  {'EV>=':>6} {'n':>7} {'n/年':>6} {'的中':>6} {'的中率':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"  {'-'*78}")
for ev_th in [0.5, 0.8, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.5, 2.0]:
    sub = [d for d in all_bets if d['ev'] >= ev_th]
    if not sub or len(sub) < 10: continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
    parts = []
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: parts.append(f"{'':>7}"); continue
        yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
        parts.append(f"{yp/yi*100:>6.1f}%")
    print(f"  {ev_th:>5.1f} {n:>7} {n/3:>6.0f} {hits:>6} {hr:>6.2%} {rec:>6.1f}% | {' '.join(parts)}")

# レース単位集計
print(f"\n--- レース単位（EV>=1.2、複数点買い） ---")
race_unit = defaultdict(lambda: {'invest':0,'payout':0,'n_bets':0,'has_hit':False,'year':0})
for d in all_bets:
    if d['ev'] < 1.2: continue
    r = race_unit[d['rid']]
    r['invest'] += 100; r['payout'] += d['payout']*100 if d['is_hit'] else 0
    r['n_bets'] += 1; r['has_hit'] = r['has_hit'] or d['is_hit']; r['year'] = d['year']
races = [v for v in race_unit.values()]
if races:
    n_r = len(races); hit_r = sum(1 for r in races if r['has_hit'])
    total_inv = sum(r['invest'] for r in races); total_pay = sum(r['payout'] for r in races)
    avg_bets = np.mean([r['n_bets'] for r in races])
    print(f"  参加R={n_r} 点/R={avg_bets:.1f} 的中R={hit_r} ({hit_r/n_r:.1%}) 回収率={total_pay/total_inv*100:.1f}%")
    for yr in [2024,2025,2026]:
        ys = [r for r in races if r['year']==yr]
        if not ys: continue
        yi = sum(r['invest'] for r in ys); yp = sum(r['payout'] for r in ys)
        print(f"    {yr}: {len(ys)}R rec={yp/yi*100:.1f}%")

# ブートストラップCI
print(f"\n--- ブートストラップCI ---")
for ev_th in [1.0, 1.2]:
    sub = [d for d in all_bets if d['ev'] >= ev_th]
    if len(sub) < 100: continue
    by_race = defaultdict(list)
    for d in sub: by_race[d['rid']].append(d)
    rids = list(by_race.keys())
    np.random.seed(42)
    br = []
    for _ in range(5000):
        samp = np.random.choice(rids, size=len(rids), replace=True)
        si=0; sp=0
        for r in samp:
            for d in by_race[r]: si+=100; sp+=d['payout']*100 if d['is_hit'] else 0
        if si>0: br.append(sp/si*100)
    br.sort()
    inv=len(sub)*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
    print(f"  EV>={ev_th}: n={len(sub):,} rec={pay/inv*100:.1f}% 95%CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

print("\nDone!")
