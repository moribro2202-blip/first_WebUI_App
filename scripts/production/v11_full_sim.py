# -*- coding: utf-8 -*-
"""v11モデル: EV帯×券種×年別シミュレーション
2022+WF、move_5to1あり、b=free
券種: 単勝, 複勝, 馬連, ワイド, 三連複
"""
import sqlite3, math, sys, numpy as np, lightgbm as lgb
from collections import defaultdict
from scipy.optimize import minimize
sys.stdout.reconfigure(encoding='utf-8')

DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'
db = sqlite3.connect(DB)
print("Loading...", flush=True)

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
ts_odds = {}
for mb in [1,5]:
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

# HJC全券種
hjc_all = defaultdict(lambda: defaultdict(dict))
for row in db.execute("SELECT race_id,bet_type,combination,odds FROM odds WHERE bet_type LIKE '%_hjc' AND odds>0").fetchall():
    hjc_all[row[0]][row[1]][row[2]] = row[3]

db.close()
print("Loaded.", flush=True)

grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}
sf_map = {'芝':0,'ダート':1}

# === データセット構築 ===
js={}; hh={}; ts_st={}
datasets={}; FNAMES=None
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
        datasets[year]={'X':[],'y':[],'init':[],'meta':[],'odds_1min':[],'probs':[]}
    hl=race_horses.get(rid,[])
    if len(hl)>=5:
        rl=result_cache.get(rid,[])
        if rl:
            winners=[r['hn'] for r in rl if r['fp']==1]
            if winners and winners[0] in hl:
                odds_mkt=ts_odds[1].get(rid,{})
                if len(odds_mkt)<len(hl)*0.8: odds_mkt=sed.get(rid,{})
                inv=np.array([1/odds_mkt.get(h,999) for h in hl])
                s=inv.sum()
                if s==0: do_update(); continue
                mp=inv/s; mp=mp**1.015; mp/=mp.sum()
                o5=ts_odds[5].get(rid,{}); o1=ts_odds[1].get(rid,{})
                has_move=len(o5)>=len(hl)*0.8 and len(o1)>=len(hl)*0.8
                entries=entry_cache.get(rid,{}); n=len(hl)
                tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
                idms=[entries.get(h,{}).get('idm') or 50 for h in hl]; avg_idm=np.mean(idms)
                riders=[entries.get(h,{}).get('rider') or 0 for h in hl]; avg_rider=np.mean(riders)
                oz=oz_cache.get(rid,{}); mkt_d=odds_mkt
                oz_inv={h:1/oz[h] if h in oz and oz[h]>0 else 0 for h in hl}
                mk_inv={h:1/mkt_d[h] if h in mkt_d and mkt_d[h]>0 else 0 for h in hl}
                oz_sum=sum(oz_inv.values()) or 1; mk_sum=sum(mk_inv.values()) or 1
                for i,h in enumerate(hl):
                    ent=entries.get(h,{}); hid=ent.get('hid','')
                    idm=ent.get('idm') or 50; rider=ent.get('rider') or 0
                    jn=ent.get('jockey',''); tn=ent.get('trainer','')
                    runs=hh.get(hid,[])
                    f={}
                    f['idm_c']=idm-avg_idm; f['rider_c']=rider-avg_rider
                    f['total_index']=ent.get('total') or 0
                    oz_p=oz_inv.get(h,0)/oz_sum; mk_p=mk_inv.get(h,0)/mk_sum
                    f['expert_resid']=math.log(max(oz_p,1e-6))-math.log(max(mk_p,1e-6)) if oz_p>0 and mk_p>0 else 0
                    jst=js.get(jn,{}); jr=jst.get('r',0)
                    f['jockey_t3rate']=jst.get('t3',0)/jr if jr>=30 else -1
                    tst=ts_st.get(tn,{}); tr_r=tst.get('r',0)
                    f['trainer_t3rate']=tst.get('t3',0)/tr_r if tr_r>=30 else -1
                    f['horse_runs']=len(runs)
                    if runs:
                        rc=runs[-5:]
                        f['avg_fp_5']=np.mean([r['fp'] for r in rc])
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
                        oo5=o5.get(h,0); oo1=o1.get(h,0)
                        f['move_5to1']=(oo5-oo1)/oo5 if oo5>0 and oo1>0 else 0
                    else: f['move_5to1']=0
                    if FNAMES is None: FNAMES=sorted(f.keys())
                    datasets[year]['X'].append([f.get(k,0) for k in FNAMES])
                    datasets[year]['y'].append(1 if h==winners[0] else 0)
                    p=mp[i]
                    datasets[year]['init'].append(math.log(max(p,1e-15))-math.log(max(1-p,1e-15)))
                    datasets[year]['meta'].append((rid,h))
                    datasets[year]['odds_1min'].append(o1.get(h,0))
    do_update()

for y in sorted(datasets.keys()):
    d=datasets[y]
    d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds_1min']=np.array(d['odds_1min'])
    print(f"  {y}: {len(d['X']):,}")

params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
        'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
        'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

# === WF + Harville-Stern ===
print("\nRunning WF...", flush=True)

all_races = []  # [{year, rid, horses, probs, results}]

for test_yr in [2024, 2025, 2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in datasets]
    fit_yr=test_yr-1
    if not train_yrs or fit_yr not in datasets or test_yr not in datasets: continue
    X_tr=np.vstack([datasets[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([datasets[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([datasets[y]['init'] for y in train_yrs])
    dtrain=lgb.Dataset(X_tr,y_tr,feature_name=FNAMES,init_score=init_tr)
    model=lgb.train(params,dtrain,num_boost_round=300)

    X_f=datasets[fit_yr]['X']; y_f=datasets[fit_yr]['y']
    init_f=datasets[fit_yr]['init']; meta_f=datasets[fit_yr]['meta']
    raw_f=model.predict(X_f,raw_score=True)
    rd_f=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_f): rd_f[rid].append(i)
    def neg_ll(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f.items():
            ys=y_f[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f[idxs]+tau*raw_f[idxs]
            s-=s.max(); nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
    b_use,tau_use=res.x
    print(f"  {test_yr}: b={b_use:.3f} tau={tau_use:.3f}")

    X_te=datasets[test_yr]['X']; y_te=datasets[test_yr]['y']
    init_te=datasets[test_yr]['init']; meta_te=datasets[test_yr]['meta']
    odds_te=datasets[test_yr]['odds_1min']
    raw_te=model.predict(X_te,raw_score=True)
    race_data=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): race_data[rid].append(i)

    for rid2,idxs in race_data.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]
        s-=s.max(); tau_p=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[i][1] for i in idxs]
        # 着順（上位3頭）
        fp_map={}
        for r in result_cache.get(rid2,[]):
            fp_map[r['hn']]=r['fp']
        all_races.append({
            'year':test_yr, 'rid':rid2,
            'horses':hns, 'probs':tau_p.tolist(),
            'odds_1min':[odds_te[idx] for idx in idxs],
            'fp_map':fp_map,
        })

print(f"Races: {len(all_races)}")

# === Harville確率 ===
def harville_top3(probs, horses):
    """Harville近似で上位3頭の確率を計算"""
    n=len(horses)
    p=np.array(probs)
    # 複勝: P(i in top3) ≈ Σ over permutations
    place_p=np.zeros(n)
    for i in range(n):
        place_p[i]=p[i]  # 1着確率
        for j in range(n):
            if j==i: continue
            p2=p[j]/(1-p[i])  # 2着確率 given i won
            place_p[i]+=p[i]*0  # iが2着
            # 簡略: place ≈ 1 - (1-p)^3 的な近似
        # Stern補正なしの簡易版
    # 簡易place確率: top3に入る確率
    for i in range(n):
        prob_not_top3=1.0
        for k in range(3):
            # k番目までに選ばれない確率
            remaining=1.0-sum(p[j] for j in range(n) if j!=i)  # rough
        place_p[i]=min(1.0, p[i]*3)  # very rough approximation
    return place_p

# === 券種別シミュレーション ===
print(f"\n{'='*90}")
print("=== 券種別 × EV帯 × 年別 シミュレーション（2024-2026）===")
print(f"{'='*90}")

# 単勝
print("\n--- 単勝 ---")
print(f"  {'EV帯':>10} | {'2024':>16} | {'2025':>16} | {'2026':>16} | {'ALL':>16}")
print(f"  {'-'*80}")

ev_bands=[(0.8,1.0),(1.0,1.1),(1.1,1.2),(1.2,1.5),(1.5,5.0)]
for lo,hi in ev_bands:
    parts=[]
    for yr in [2024,2025,2026,'ALL']:
        n=0; invest=0; payout=0
        for race in all_races:
            if yr!='ALL' and race['year']!=yr: continue
            for i,hn in enumerate(race['horses']):
                o=race['odds_1min'][i]
                if o<=0: continue
                ev=race['probs'][i]*o
                if lo<=ev<hi:
                    n+=1; invest+=100
                    if race['fp_map'].get(hn)==1:
                        hjc_w=hjc_all.get(race['rid'],{}).get('win_hjc',{}).get(str(hn),0)
                        payout+=hjc_w*100
        rec=payout/invest*100 if invest>0 else 0
        parts.append(f"n={n:>5} {rec:>5.1f}%")
    label=f"{lo:.1f}-{hi:.1f}"
    print(f"  {label:>10} | {' | '.join(parts)}")

# 複勝
print("\n--- 複勝 ---")
print(f"  {'EV帯':>10} | {'2024':>16} | {'2025':>16} | {'2026':>16} | {'ALL':>16}")
print(f"  {'-'*80}")
for lo,hi in ev_bands:
    parts=[]
    for yr in [2024,2025,2026,'ALL']:
        n=0; invest=0; payout=0
        for race in all_races:
            if yr!='ALL' and race['year']!=yr: continue
            for i,hn in enumerate(race['horses']):
                o=race['odds_1min'][i]
                if o<=0: continue
                # 複勝EV ≈ place_prob * place_odds
                # 簡易: place_prob ≈ min(1, win_prob * 3)
                place_p=min(1.0, race['probs'][i]*3)
                # 複勝オッズはHJCから
                hjc_place=hjc_all.get(race['rid'],{}).get('place_hjc',{}).get(str(hn),0)
                if hjc_place<=0: continue
                ev_place=place_p*hjc_place
                if lo<=ev_place<hi:
                    n+=1; invest+=100
                    if race['fp_map'].get(hn,99)<=3:
                        payout+=hjc_place*100
        rec=payout/invest*100 if invest>0 else 0
        parts.append(f"n={n:>5} {rec:>5.1f}%")
    label=f"{lo:.1f}-{hi:.1f}"
    print(f"  {label:>10} | {' | '.join(parts)}")

# 馬連（◎○の2頭）
print("\n--- 馬連（モデル上位2頭）---")
print(f"  {'EV帯':>10} | {'2024':>16} | {'2025':>16} | {'2026':>16} | {'ALL':>16}")
print(f"  {'-'*80}")
umaren_bands=[(0.5,1.0),(1.0,1.5),(1.5,2.0),(2.0,5.0),(5.0,50.0)]
for lo,hi in umaren_bands:
    parts=[]
    for yr in [2024,2025,2026,'ALL']:
        n=0; invest=0; payout=0
        for race in all_races:
            if yr!='ALL' and race['year']!=yr: continue
            if len(race['horses'])<5: continue
            sorted_idx=np.argsort(race['probs'])[::-1]
            h1=race['horses'][sorted_idx[0]]
            h2=race['horses'][sorted_idx[1]]
            p1=race['probs'][sorted_idx[0]]
            p2_given=race['probs'][sorted_idx[1]]/(1-p1)
            combo_p=p1*p2_given*2  # 馬連（順序不問）
            combo_key='-'.join(str(x) for x in sorted([h1,h2]))
            hjc_umaren=hjc_all.get(race['rid'],{}).get('umaren_hjc',{}).get(combo_key,0)
            if hjc_umaren<=0: continue
            ev_u=combo_p*hjc_umaren
            if lo<=ev_u<hi:
                n+=1; invest+=100
                fp1=race['fp_map'].get(h1,99)
                fp2=race['fp_map'].get(h2,99)
                if set([fp1,fp2])==set([1,2]):
                    payout+=hjc_umaren*100
        rec=payout/invest*100 if invest>0 else 0
        parts.append(f"n={n:>5} {rec:>5.1f}%")
    label=f"{lo:.1f}-{hi:.1f}"
    print(f"  {label:>10} | {' | '.join(parts)}")

# ワイド（◎○の2頭）
print("\n--- ワイド（モデル上位2頭）---")
print(f"  {'EV帯':>10} | {'2024':>16} | {'2025':>16} | {'2026':>16} | {'ALL':>16}")
print(f"  {'-'*80}")
for lo,hi in [(0.5,1.0),(1.0,1.2),(1.2,1.5),(1.5,3.0),(3.0,50.0)]:
    parts=[]
    for yr in [2024,2025,2026,'ALL']:
        n=0; invest=0; payout=0
        for race in all_races:
            if yr!='ALL' and race['year']!=yr: continue
            if len(race['horses'])<5: continue
            sorted_idx=np.argsort(race['probs'])[::-1]
            h1=race['horses'][sorted_idx[0]]
            h2=race['horses'][sorted_idx[1]]
            p1=race['probs'][sorted_idx[0]]
            p2=race['probs'][sorted_idx[1]]
            # ワイド確率 ≈ 両方top3に入る確率（簡易）
            wide_p=min(1.0,p1*3)*min(1.0,p2*3)*0.33  # rough
            combo_key='-'.join(str(x) for x in sorted([h1,h2]))
            hjc_wide=hjc_all.get(race['rid'],{}).get('wide_hjc',{}).get(combo_key,0)
            if hjc_wide<=0: continue
            ev_w=wide_p*hjc_wide
            if lo<=ev_w<hi:
                n+=1; invest+=100
                fp1=race['fp_map'].get(h1,99)
                fp2=race['fp_map'].get(h2,99)
                if fp1<=3 and fp2<=3:
                    payout+=hjc_wide*100
        rec=payout/invest*100 if invest>0 else 0
        parts.append(f"n={n:>5} {rec:>5.1f}%")
    label=f"{lo:.1f}-{hi:.1f}"
    print(f"  {label:>10} | {' | '.join(parts)}")

# 三連複（◎○▲の3頭）
print("\n--- 三連複（モデル上位3頭）---")
print(f"  {'EV帯':>10} | {'2024':>16} | {'2025':>16} | {'2026':>16} | {'ALL':>16}")
print(f"  {'-'*80}")
for lo,hi in [(0.5,1.0),(1.0,2.0),(2.0,5.0),(5.0,20.0),(20.0,500.0)]:
    parts=[]
    for yr in [2024,2025,2026,'ALL']:
        n=0; invest=0; payout=0
        for race in all_races:
            if yr!='ALL' and race['year']!=yr: continue
            if len(race['horses'])<5: continue
            sorted_idx=np.argsort(race['probs'])[::-1]
            h1=race['horses'][sorted_idx[0]]
            h2=race['horses'][sorted_idx[1]]
            h3=race['horses'][sorted_idx[2]]
            p1=race['probs'][sorted_idx[0]]
            p2=race['probs'][sorted_idx[1]]
            p3=race['probs'][sorted_idx[2]]
            # 三連複確率（Harville簡易）
            trio_p=p1*p2/(1-p1)*p3/(1-p1-p2)*6  # 6 permutations
            trio_p=min(trio_p, 0.5)
            combo_key='-'.join(str(x) for x in sorted([h1,h2,h3]))
            hjc_trio=hjc_all.get(race['rid'],{}).get('sanrenpuku_hjc',{}).get(combo_key,0)
            if hjc_trio<=0: continue
            ev_t=trio_p*hjc_trio
            if lo<=ev_t<hi:
                n+=1; invest+=100
                fps=set([race['fp_map'].get(h1,99),race['fp_map'].get(h2,99),race['fp_map'].get(h3,99)])
                if fps==set([1,2,3]):
                    payout+=hjc_trio*100
        rec=payout/invest*100 if invest>0 else 0
        parts.append(f"n={n:>5} {rec:>5.1f}%")
    label=f"{lo:.1f}-{hi:.1f}"
    print(f"  {label:>10} | {' | '.join(parts)}")

# === 券種サマリー（EV>=1.0） ===
print(f"\n{'='*90}")
print("=== 券種サマリー（EV>=1.0）===")
print(f"{'='*90}")
# 既に上の表で読み取れるが、一覧を出す

print("\nDone!")
