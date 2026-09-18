# -*- coding: utf-8 -*-
"""v19b: 単勝エッジ（モデル確率/市場確率）を使った連系券種戦略
モデルが市場より高く評価した馬（エッジ馬）を軸に連系を組む

戦略A: エッジ馬のみで連系（edge >= threshold）
戦略B: エッジ馬 × 上位人気（軸-相手）
戦略C: 単勝EV >= 1.0 の馬同士の組合せ
各戦略 × 券種 × EV(SH確率×プール実オッズ) でフィルタ
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

print("  confirmed_odds: on-demand query mode", flush=True)
# メモリ節約のためレースごとにクエリ
conf_db_path = DB  # 後でクエリ用に保持

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
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

def stern_harville_full(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    wide=defaultdict(float); umaren=defaultdict(float)
    trio=defaultdict(float); trifecta=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            umaren[tuple(sorted([i,j]))]+=pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                for a,b in combinations(sorted([i,j,k]),2): wide[(a,b)]+=pijk
                trio[tuple(sorted([i,j,k]))]+=pijk
                trifecta[(i,j,k)]+=pijk
    return wide, umaren, trio, trifecta

# データセット構築
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
        datasets[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    hl=race_horses.get(rid,[])
    if len(hl)>=5:
        rl=result_cache.get(rid,[])
        if rl:
            winners=[r['hn'] for r in rl if r['fp']==1]
            if winners and winners[0] in hl:
                odds_mkt=ts3.get(rid,{})
                if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
                inv=np.array([1/odds_mkt.get(h,999) for h in hl])
                s=inv.sum()
                if s==0: do_update(); continue
                mp=inv/s; mp=mp**1.015; mp/=mp.sum()
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
                    f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
                    f['gate_ratio']=h/n
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
                    datasets[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
                    datasets[year]['meta'].append((rid,h))
                    datasets[year]['odds'].append(o3.get(h,0))
    do_update()
for y in sorted(datasets.keys()):
    d=datasets[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
    print(f"  {y}: {len(d['X']):,}")

lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

# === WF + エッジベース連系 ===
print("\nRunning WF...", flush=True)

# 全戦略の結果を格納
results = defaultdict(list)

for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in datasets]
    fit_yr=test_yr-1
    if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
    X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
    dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr)
    model=lgb.train(lgb_params,dtrain,num_boost_round=300)
    X_f=datasets[fit_yr]['X']; y_f=datasets[fit_yr]['y']; init_f=datasets[fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True)
    rd_f=defaultdict(list)
    for i,(rid,hn) in enumerate(datasets[fit_yr]['meta']): rd_f[rid].append(i)
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
    print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")

    X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']; init_te=datasets[test_yr]['init']
    meta_te=datasets[test_yr]['meta']; odds_te=datasets[test_yr]['odds']
    raw_te=model.predict(X_te,raw_score=True)
    race_data=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): race_data[rid].append(i)

    n_proc = 0
    for rid2, idxs in race_data.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
        p_model=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[i][1] for i in idxs]
        fps=result_full.get(rid2,{})
        hjc=hjc_all.get(rid2,{})
        # confirmed_oddsをレースごとにクエリ
        cdb = sqlite3.connect(conf_db_path, timeout=30)
        co = defaultdict(dict)
        for row in cdb.execute("SELECT bet_type,combination,odds FROM confirmed_odds WHERE race_id=? AND odds>0 AND bet_type IN ('umaren','wide','sanrenpuku','sanrentan')", (rid2,)).fetchall():
            co[row[0]][row[1]] = row[2]
        cdb.close()

        # 市場確率（3分前オッズから）
        mkt_odds = {hns[j]: odds_te[idxs[j]] for j in range(len(hns))}
        inv_arr = np.array([1/max(mkt_odds.get(h,999),0.001) for h in hns])
        p_market = inv_arr / inv_arr.sum()

        # エッジ: model_prob / market_prob
        edges = {}
        win_evs = {}
        for j, h in enumerate(hns):
            o = mkt_odds.get(h, 0)
            edge = p_model[j] / max(p_market[j], 1e-8)
            edges[h] = edge
            win_evs[h] = p_model[j] * o if o > 0 else 0

        # SH確率
        wide_p, umaren_p, trio_p, trifecta_p = stern_harville_full(p_model)

        # === 戦略別にベット生成 ===

        # エッジ馬を特定（edge >= threshold）
        for edge_th in [1.1, 1.2, 1.3]:
            edge_horses = [h for h in hns if edges.get(h, 0) >= edge_th]
            if len(edge_horses) < 2: continue

            # 相手候補: 上位6頭（モデル順位）
            rank_order = np.argsort(p_model)[::-1]
            top6_hns = [hns[i] for i in rank_order[:min(6, len(rank_order))]]

            # 戦略A: エッジ馬同士の組合せ
            for a, b in combinations(edge_horses, 2):
                ai = hns.index(a); bi = hns.index(b)
                key = tuple(sorted([ai, bi]))

                # 馬連
                um_p = umaren_p.get(key, 0)
                if um_p > 0:
                    combo = '-'.join(str(x) for x in sorted([a, b]))
                    pool_o = co.get('umaren', {}).get(combo, 0)
                    if pool_o > 0:
                        ev = um_p * pool_o
                        fp1, fp2 = fps.get(a, 99), fps.get(b, 99)
                        is_hit = int(set([fp1, fp2]) == set([1, 2]))
                        payout = hjc.get('umaren_hjc', {}).get(combo, 0) if is_hit else 0
                        results[f'馬連_edgeA{edge_th}'].append({
                            'year': test_yr, 'ev': ev, 'is_hit': is_hit,
                            'payout': payout, 'rid': rid2, 'pool_odds': pool_o})

                # ワイド
                w_p = wide_p.get(key, 0)
                if w_p > 0:
                    combo = '-'.join(str(x) for x in sorted([a, b]))
                    pool_o = co.get('wide', {}).get(combo, 0)
                    if pool_o > 0:
                        ev = w_p * pool_o
                        fp1, fp2 = fps.get(a, 99), fps.get(b, 99)
                        is_hit = int(fp1 <= 3 and fp2 <= 3)
                        payout = hjc.get('wide_hjc', {}).get(combo, 0) if is_hit else 0
                        results[f'ワイド_edgeA{edge_th}'].append({
                            'year': test_yr, 'ev': ev, 'is_hit': is_hit,
                            'payout': payout, 'rid': rid2, 'pool_odds': pool_o})

            # 三連複: エッジ馬3頭以上
            if len(edge_horses) >= 3:
                for a, b, c in combinations(edge_horses[:6], 3):
                    ai, bi, ci = hns.index(a), hns.index(b), hns.index(c)
                    key = tuple(sorted([ai, bi, ci]))
                    tr_p = trio_p.get(key, 0)
                    if tr_p <= 0: continue
                    combo = '-'.join(str(x) for x in sorted([a, b, c]))
                    pool_o = co.get('sanrenpuku', {}).get(combo, 0)
                    if pool_o <= 0: continue
                    ev = tr_p * pool_o
                    fps3 = set([fps.get(a, 99), fps.get(b, 99), fps.get(c, 99)])
                    is_hit = int(fps3 == set([1, 2, 3]))
                    payout = hjc.get('sanrenpuku_hjc', {}).get(combo, 0) if is_hit else 0
                    results[f'三連複_edgeA{edge_th}'].append({
                        'year': test_yr, 'ev': ev, 'is_hit': is_hit,
                        'payout': payout, 'rid': rid2, 'pool_odds': pool_o})

            # 戦略B: エッジ馬（軸） × 上位人気（相手）
            for edge_h in edge_horses:
                ei = hns.index(edge_h)
                for partner_h in top6_hns:
                    if partner_h == edge_h: continue
                    pi = hns.index(partner_h)
                    key = tuple(sorted([ei, pi]))

                    # 馬連
                    um_p = umaren_p.get(key, 0)
                    if um_p > 0:
                        combo = '-'.join(str(x) for x in sorted([edge_h, partner_h]))
                        pool_o = co.get('umaren', {}).get(combo, 0)
                        if pool_o > 0:
                            ev = um_p * pool_o
                            fp1, fp2 = fps.get(edge_h, 99), fps.get(partner_h, 99)
                            is_hit = int(set([fp1, fp2]) == set([1, 2]))
                            payout = hjc.get('umaren_hjc', {}).get(combo, 0) if is_hit else 0
                            results[f'馬連_edgeB{edge_th}'].append({
                                'year': test_yr, 'ev': ev, 'is_hit': is_hit,
                                'payout': payout, 'rid': rid2, 'pool_odds': pool_o})

        # 戦略C: 単勝EV>=1.0の馬同士
        ev_horses = [h for h in hns if win_evs.get(h, 0) >= 1.0]
        if len(ev_horses) >= 2:
            for a, b in combinations(ev_horses[:6], 2):
                ai, bi = hns.index(a), hns.index(b)
                key = tuple(sorted([ai, bi]))
                um_p = umaren_p.get(key, 0)
                if um_p > 0:
                    combo = '-'.join(str(x) for x in sorted([a, b]))
                    pool_o = co.get('umaren', {}).get(combo, 0)
                    if pool_o > 0:
                        ev = um_p * pool_o
                        fp1, fp2 = fps.get(a, 99), fps.get(b, 99)
                        is_hit = int(set([fp1, fp2]) == set([1, 2]))
                        payout = hjc.get('umaren_hjc', {}).get(combo, 0) if is_hit else 0
                        results['馬連_winEV1.0'].append({
                            'year': test_yr, 'ev': ev, 'is_hit': is_hit,
                            'payout': payout, 'rid': rid2, 'pool_odds': pool_o})

                w_p = wide_p.get(key, 0)
                if w_p > 0:
                    combo = '-'.join(str(x) for x in sorted([a, b]))
                    pool_o = co.get('wide', {}).get(combo, 0)
                    if pool_o > 0:
                        ev = w_p * pool_o
                        fp1, fp2 = fps.get(a, 99), fps.get(b, 99)
                        is_hit = int(fp1 <= 3 and fp2 <= 3)
                        payout = hjc.get('wide_hjc', {}).get(combo, 0) if is_hit else 0
                        results['ワイド_winEV1.0'].append({
                            'year': test_yr, 'ev': ev, 'is_hit': is_hit,
                            'payout': payout, 'rid': rid2, 'pool_odds': pool_o})

        n_proc += 1
        if n_proc % 1000 == 0:
            print(f"    {test_yr}: {n_proc}R", flush=True)

# === 結果表示 ===
print(f"\n{'='*90}")
print("v19b: エッジベース連系戦略")
print(f"{'='*90}")

print(f"\n{'戦略':>20} {'n':>7} {'的中':>6} {'的中率':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"{'-'*80}")

# 全戦略をEV>=1.0でまず表示
for strat in sorted(results.keys()):
    data = results[strat]
    if not data: continue
    # EV>=1.0フィルタなし（全ベット）
    n = len(data); hits = sum(d['is_hit'] for d in data); hr = hits/n if n else 0
    inv = n*100; pay = sum(d['payout']*100 for d in data if d['is_hit'])
    rec = pay/inv*100 if inv > 0 else 0
    parts = []
    for yr in [2024,2025,2026]:
        ys = [d for d in data if d['year']==yr]
        if not ys: parts.append(f"{'':>7}"); continue
        yi = len(ys)*100; yp = sum(d['payout']*100 for d in ys if d['is_hit'])
        parts.append(f"{yp/yi*100:>6.1f}%")
    print(f"{strat:>20} {n:>7} {hits:>6} {hr:>6.2%} {rec:>6.1f}% | {' '.join(parts)}")

# EV閾値別の詳細
print(f"\n{'='*90}")
print("EV閾値別 詳細")
print(f"{'='*90}")

for strat in sorted(results.keys()):
    data = results[strat]
    if not data or len(data) < 50: continue
    print(f"\n--- {strat} ---")
    print(f"  {'EV>=':>6} {'n':>7} {'的中':>6} {'的中率':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
    print(f"  {'-'*75}")
    for ev_th in [0.8, 1.0, 1.1, 1.2, 1.3, 1.5, 2.0]:
        sub = [d for d in data if d['ev'] >= ev_th]
        if not sub or len(sub) < 10: continue
        n = len(sub); hits = sum(d['is_hit'] for d in sub); hr = hits/n
        inv = n*100; pay = sum(d['payout']*100 for d in sub if d['is_hit'])
        rec = pay/inv*100 if inv > 0 else 0
        parts = []
        for yr in [2024,2025,2026]:
            ys = [d for d in sub if d['year']==yr]
            if not ys: parts.append(f"{'':>7}"); continue
            yi = len(ys)*100; yp = sum(d['payout']*100 for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:>6.1f}%")
        print(f"  {ev_th:>5.1f} {n:>7} {hits:>6} {hr:>6.2%} {rec:>6.1f}% | {' '.join(parts)}")

# ブートストラップCI（上位戦略のみ）
print(f"\n{'='*90}")
print("ブートストラップCI（回収率95%+の戦略、EV>=1.0）")
print(f"{'='*90}")
for strat in sorted(results.keys()):
    data = [d for d in results[strat] if d['ev'] >= 1.0]
    if len(data) < 100: continue
    inv = len(data)*100; pay = sum(d['payout']*100 for d in data if d['is_hit'])
    rec = pay/inv*100
    if rec < 95: continue
    by_race = defaultdict(list)
    for d in data: by_race[d['rid']].append(d)
    rids = list(by_race.keys())
    np.random.seed(42)
    br = []
    for _ in range(5000):
        samp = np.random.choice(rids, size=len(rids), replace=True)
        si = 0; sp = 0
        for r in samp:
            for d in by_race[r]: si += 100; sp += d['payout']*100 if d['is_hit'] else 0
        if si > 0: br.append(sp/si*100)
    br.sort()
    print(f"  {strat}: n={len(data):,} rec={rec:.1f}% 95%CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

print("\nDone!")
