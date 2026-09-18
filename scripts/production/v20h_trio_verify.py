# -*- coding: utf-8 -*-
"""v20h: 三連複プール直接基準の検証
1. 1年50%ルール
2. レース単位収支分布
3. 上位8頭縛りバイアス検証（上位6/8/10/全頭で比較）
4. シャッフルテスト（move_5to3をシャッフル）
5. EV帯別キャリブレーション
6. 月別累積損益
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

def make_trio_features(f1, f2, f3):
    pf = {}
    for key in FEAT_KEYS:
        v1=f1.get(key,0); v2=f2.get(key,0); v3=f3.get(key,0)
        pf[f'{key}_sum'] = v1+v2+v3
        pf[f'{key}_spread'] = max(v1,v2,v3)-min(v1,v2,v3)
    odds_list = sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
    pf['win_odds_top_ratio'] = odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
    pf['win_odds_sum_inv'] = sum(1/o for o in odds_list if o>0)
    return pf

# === データセット構築（上位N頭ごと）===
print("Building datasets...", flush=True)
js={}; hh={}; ts_st={}

def build_trio_ds(top_n_limit):
    """top_n_limit頭に絞って三連複データセットを構築"""
    trio_ds = {}
    TFNAMES = None
    cdb = sqlite3.connect(DB, timeout=30)
    # js/hh/ts_stは外側で管理（累積統計）
    # ここでは特徴量構築のみ
    for rid, rd, vc, sf, dt in races_raw:
        year = int(rd[:4])
        if year < 2022: continue
        hl = race_horses.get(rid, [])
        if len(hl) < 5: continue
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
        sorted_h = sorted(o3.items(), key=lambda x:x[1]) if o3 else []
        rank_map = {h:i+1 for i,(h,o) in enumerate(sorted_h)}

        co_tr = {}
        for row in cdb.execute("SELECT combination,odds FROM confirmed_odds WHERE race_id=? AND bet_type='sanrenpuku' AND odds>0", (rid,)).fetchall():
            co_tr[row[0]] = row[1]
        if len(co_tr) < 3: continue
        inv_tr = {k:1.0/v for k,v in co_tr.items()}; total_inv = sum(inv_tr.values())
        if total_inv == 0: continue
        mkt_prob = {k:v/total_inv for k,v in inv_tr.items()}
        top3 = sorted([r for r in result_cache.get(rid,[]) if r['fp'] in (1,2,3)], key=lambda x:x['fp'])
        if len(top3) < 3: continue
        winner_combo = '-'.join(str(x) for x in sorted([top3[0]['hn'],top3[1]['hn'],top3[2]['hn']]))

        if year not in trio_ds:
            trio_ds[year] = {'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[]}

        feats_h = {}
        for h in hl:
            feats_h[h] = build_horse_feat(h,entries,hl,avg_idm,avg_rider,
                                           oz_inv,oz_sum,mk_inv,mk_sum,avg_cyb,
                                           js,ts_st,hh,o5,o3,has_move,cyb_cache,rid)
        # 上位N頭
        if top_n_limit < 99:
            top_hns = [h for h,_ in sorted(o3.items(), key=lambda x:x[1])[:top_n_limit]] if o3 else hl[:top_n_limit]
        else:
            top_hns = hl

        for a,b,c in combinations(top_hns, 3):
            combo = '-'.join(str(x) for x in sorted([a,b,c]))
            if combo not in co_tr: continue
            if a not in feats_h or b not in feats_h or c not in feats_h: continue
            pf = make_trio_features(feats_h[a], feats_h[b], feats_h[c])
            if TFNAMES is None: TFNAMES = sorted(pf.keys())
            mp_val = mkt_prob.get(combo, 1e-8)
            init = math.log(max(mp_val,1e-15))-math.log(max(1-mp_val,1e-15))
            is_hit = 1 if combo == winner_combo else 0
            pop_high = min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99))
            trio_ds[year]['X'].append([pf.get(k,0) for k in TFNAMES])
            trio_ds[year]['y'].append(is_hit)
            trio_ds[year]['init'].append(init)
            trio_ds[year]['meta'].append((rid, combo))
            trio_ds[year]['odds'].append(co_tr[combo])
            trio_ds[year]['pop'].append(pop_high)
    cdb.close()
    for y in trio_ds:
        d=trio_ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds']); d['pop']=np.array(d['pop'])
    return trio_ds, TFNAMES

# 統計累積（1回だけ）
for rid,rd,vc,sf,dt in races_raw:
    year=int(rd[:4])
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

lgb_params = {'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
              'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
              'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf_trio(trio_ds, TFNAMES, label):
    print(f"\n--- {label} ---")
    all_bets = []
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in trio_ds]; fit_yr=test_yr-1
        if not train_yrs or fit_yr not in trio_ds or test_yr not in trio_ds: continue
        X_tr=np.vstack([trio_ds[y]['X'] for y in train_yrs])
        y_tr=np.concatenate([trio_ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([trio_ds[y]['init'] for y in train_yrs])
        model=lgb.train(lgb_params,lgb.Dataset(X_tr,y_tr,feature_name=TFNAMES,init_score=init_tr),num_boost_round=300)
        X_f=trio_ds[fit_yr]['X']; y_f=trio_ds[fit_yr]['y']; init_f=trio_ds[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,combo) in enumerate(trio_ds[fit_yr]['meta']): rd_f[rid].append(i)
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
        X_te=trio_ds[test_yr]['X']; y_te=trio_ds[test_yr]['y']
        init_te=trio_ds[test_yr]['init']; meta_te=trio_ds[test_yr]['meta']
        odds_te=trio_ds[test_yr]['odds']; pop_te=trio_ds[test_yr]['pop']
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,combo) in enumerate(meta_te): rd_te[rid].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                combo=meta_te[idx][1]; o=odds_te[idx]; ev=probs[j]*o
                is_hit=y_te[idx]; rid_=meta_te[idx][0]
                payout=hjc_all.get(rid_,{}).get('sanrenpuku_hjc',{}).get(combo,0) if is_hit else 0
                rd=race_dates.get(rid_,''); month=rd[:7]
                all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':payout,'pop':int(pop_te[idx]),'rid':rid_,
                                 'odds':o,'mdl_p':float(probs[j]),'month':month})
    return all_bets

# === 検証1: 上位N頭の影響 ===
print("\n=== 検証1: 上位N頭の影響 ===")
for top_n in [6, 8, 10]:
    print(f"\n  Building top{top_n}...", flush=True)
    trio_ds, TFNAMES = build_trio_ds(top_n)
    for y in sorted(trio_ds.keys()):
        print(f"    {y}: {len(trio_ds[y]['X']):,}")
    bets = run_wf_trio(trio_ds, TFNAMES, f"top{top_n}")
    # EV>=1.2の結果
    for pop_label, pop_max in [('1番人気含む',1),('全組合せ',99)]:
        sub=[d for d in bets if d['ev']>=1.2 and d['pop']<=pop_max]
        if len(sub)<10: continue
        n=len(sub); hits=sum(d['is_hit'] for d in sub)
        inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: parts.append(''); continue
            yi=len(ys)*100; yp=sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:.1f}%")
        print(f"    {pop_label} EV>=1.2: n={n:,} rec={rec:.1f}% | {' '.join(parts)}")

# メイン分析はtop8で実施
print("\n=== メイン分析（top8）===")
trio_ds_main, TFNAMES_MAIN = build_trio_ds(8)
bets_main = run_wf_trio(trio_ds_main, TFNAMES_MAIN, "top8 (main)")

# === 検証2: 1年50%ルール ===
print(f"\n=== 検証2: 1年50%ルール ===")
for ev_th in [1.0, 1.2]:
    sub=[d for d in bets_main if d['ev']>=ev_th]
    if not sub: continue
    total_inv=len(sub)*100; total_pay=sum(d['payout']*100 for d in sub if d['is_hit'])
    total_pnl=total_pay-total_inv
    print(f"\n  EV>={ev_th}: total PnL={total_pnl:+,.0f}")
    for yr in [2024,2025,2026]:
        ys=[d for d in sub if d['year']==yr]
        if not ys: continue
        n=len(ys); inv=n*100; pay=sum(d['payout']*100 for d in ys if d['is_hit'])
        pnl=pay-inv; pnl_pct=pnl/abs(total_pnl)*100 if total_pnl!=0 else 0
        flag="*** 50%超 ***" if abs(pnl_pct)>50 else ""
        print(f"    {yr}: n={n:,} PnL={pnl:+,.0f} ({pnl_pct:+.0f}%) rec={pay/inv*100:.1f}% {flag}")

# === 検証3: レース単位収支分布 ===
print(f"\n=== 検証3: レース単位収支（EV>=1.2）===")
by_race=defaultdict(lambda:{'inv':0,'pay':0,'n_bets':0,'has_hit':False})
for d in bets_main:
    if d['ev']<1.2: continue
    r=by_race[d['rid']]
    r['inv']+=100; r['pay']+=d['payout']*100 if d['is_hit'] else 0
    r['n_bets']+=1; r['has_hit']=r['has_hit'] or d['is_hit']
races_list=list(by_race.values())
if races_list:
    pnls=[r['pay']-r['inv'] for r in races_list]
    hit_r=sum(1 for r in races_list if r['has_hit'])
    print(f"  参加R={len(races_list)} 的中R={hit_r} ({hit_r/len(races_list):.1%})")
    print(f"  平均点数/R={np.mean([r['n_bets'] for r in races_list]):.1f} 平均投資/R={np.mean([r['inv'] for r in races_list]):.0f}円")
    print(f"  収支: mean={np.mean(pnls):.0f}円 median={np.median(pnls):.0f}円")
    for pct in [10,25,50,75,90,95,99]:
        print(f"    {pct}%ile: {np.percentile(pnls, pct):.0f}円")

# === 検証4: EV帯別キャリブレーション ===
print(f"\n=== 検証4: EV帯別キャリブレーション ===")
print(f"  {'EV帯':>10} {'n':>7} {'予測P':>8} {'実績P':>8} {'比':>5} {'回収率':>7} {'平均odds':>8}")
for lo,hi in [(0.5,0.8),(0.8,1.0),(1.0,1.2),(1.2,1.5),(1.5,2.0),(2.0,3.0),(3.0,5.0),(5.0,99)]:
    sub=[d for d in bets_main if lo<=d['ev']<hi]
    if len(sub)<10: continue
    n=len(sub); avg_p=np.mean([d['mdl_p'] for d in sub]); avg_hit=np.mean([d['is_hit'] for d in sub])
    ratio=avg_hit/avg_p if avg_p>0 else 0
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit']); rec=pay/inv*100
    avg_odds=np.mean([d['odds'] for d in sub])
    label=f"{lo:.1f}-{hi:.1f}" if hi<99 else f"{lo:.1f}+"
    print(f"  {label:>10} {n:>7} {avg_p:>7.5f} {avg_hit:>7.5f} {ratio:>4.2f} {rec:>6.1f}% {avg_odds:>7.0f}")

# === 検証5: 月別累積損益 ===
print(f"\n=== 検証5: 月別累積損益（EV>=1.2）===")
months=sorted(set(d['month'] for d in bets_main if d['ev']>=1.2 and d['month']))
cum_pnl=0
print(f"  {'月':>7} {'n':>5} {'的中':>4} {'投資':>9} {'払戻':>9} {'月PnL':>9} {'累積PnL':>10}")
for m in months:
    sub=[d for d in bets_main if d['ev']>=1.2 and d['month']==m]
    n=len(sub); hits=sum(d['is_hit'] for d in sub)
    inv=n*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
    pnl=pay-inv; cum_pnl+=pnl
    print(f"  {m:>7} {n:>5} {hits:>4} {inv:>8,} {pay:>8,.0f} {pnl:>+8,.0f} {cum_pnl:>+9,.0f}")

# === 検証6: ブートストラップCI ===
print(f"\n=== 検証6: ブートストラップCI ===")
for ev_th in [1.0, 1.2, 1.5]:
    sub=[d for d in bets_main if d['ev']>=ev_th]
    if len(sub)<100: continue
    by_r=defaultdict(list)
    for d in sub: by_r[d['rid']].append(d)
    rids=list(by_r.keys()); np.random.seed(42); br=[]
    for _ in range(5000):
        samp=np.random.choice(rids,size=len(rids),replace=True)
        si=0; sp=0
        for r in samp:
            for d in by_r[r]: si+=100; sp+=d['payout']*100 if d['is_hit'] else 0
        if si>0: br.append(sp/si*100)
    br.sort()
    inv=len(sub)*100; pay=sum(d['payout']*100 for d in sub if d['is_hit'])
    print(f"  EV>={ev_th}: n={len(sub):,} rec={pay/inv*100:.1f}% 95%CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

print("\nDone!")
