# -*- coding: utf-8 -*-
"""v21b: 三連複 SH基準の詳細分析
- レース単位収支
- 1番人気含む vs 含まない
- オッズ帯別
- 月別累積
- 1年50%ルール
- レースあたりの点数分布
- ブートストラップCI
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

LAM2, LAM3 = 0.8076, 0.6978
TAKEOUT_TRIO = 0.25
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_trio(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float)
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(p[i]/S1)*(p2[j]/d2)
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                trio[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    return trio

# データセット
js={}; hh={}; ts_st={}; tr_ds={}; TRFNAMES=None
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
    winners=[r['hn'] for r in rl if r['fp']==1]
    if not winners or winners[0] not in hl: do_update(); continue
    o3=ts3.get(rid,{}); o5=ts5.get(rid,{})
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
    fps=result_full.get(rid,{}); hjc=hjc_all.get(rid,{}); month=rd[:7]
    trio_mkt=sh_trio(mp)
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}
    top8=[h for h,_ in sorted_h[:8]] if sorted_h else hl[:8]
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    if len(top3_fps)<3: do_update(); continue
    winner_tr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
    if year not in tr_ds: tr_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[],'pop':[],'month':[],'hjc_payout':[]}
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
    for a,b,c in combinations(top8,3):
        ai=hl.index(a); bi=hl.index(b); ci=hl.index(c)
        key=tuple(sorted([ai,bi,ci]))
        sh_p=trio_mkt.get(key,0)
        if sh_p<=0: continue
        combo='-'.join(str(x) for x in sorted([a,b,c]))
        est_odds=(1/sh_p)*(1-TAKEOUT_TRIO)
        pf={}
        f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
        for k in FEAT_KEYS:
            v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
            pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
        odds_list=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
        pf['win_odds_top_ratio']=odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
        pf['win_odds_sum_inv']=sum(1/o for o in odds_list if o>0)
        if TRFNAMES is None: TRFNAMES=sorted(pf.keys())
        init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
        is_hit=1 if combo==winner_tr else 0
        payout=hjc.get('sanrenpuku_hjc',{}).get(combo,0) if is_hit else 0
        pop=min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99))
        tr_ds[year]['X'].append([pf.get(k,0) for k in TRFNAMES])
        tr_ds[year]['y'].append(is_hit); tr_ds[year]['init'].append(init)
        tr_ds[year]['meta'].append((rid,combo)); tr_ds[year]['odds'].append(est_odds)
        tr_ds[year]['pop'].append(pop); tr_ds[year]['month'].append(month)
        tr_ds[year]['hjc_payout'].append(payout)
    do_update()
for y in tr_ds:
    d=tr_ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
    d['pop']=np.array(d['pop']); d['hjc_payout']=np.array(d['hjc_payout'])
    print(f"  {y}: {len(d['X']):,}")

# WF
lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
print("\nWF...", flush=True)
all_bets=[]
for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in tr_ds]; fit_yr=test_yr-1
    if not train_yrs or fit_yr not in tr_ds or test_yr not in tr_ds: continue
    X_tr=np.vstack([tr_ds[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([tr_ds[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([tr_ds[y]['init'] for y in train_yrs])
    model=lgb.train(lgb_params,lgb.Dataset(X_tr,y_tr,feature_name=TRFNAMES,init_score=init_tr),num_boost_round=300)
    X_f=tr_ds[fit_yr]['X']; y_f=tr_ds[fit_yr]['y']; init_f=tr_ds[fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True)
    rd_f=defaultdict(list)
    for i,(rid,combo) in enumerate(tr_ds[fit_yr]['meta']): rd_f[rid].append(i)
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
    imp=model.feature_importance(importance_type='gain')
    top5=sorted(zip(TRFNAMES,imp),key=lambda x:-x[1])[:5]
    print(f"    top5: {[(f,f'{g:.0f}') for f,g in top5]}")
    X_te=tr_ds[test_yr]['X']; y_te=tr_ds[test_yr]['y']; init_te=tr_ds[test_yr]['init']
    meta_te=tr_ds[test_yr]['meta']; odds_te=tr_ds[test_yr]['odds']
    pop_te=tr_ds[test_yr]['pop']; month_te=tr_ds[test_yr]['month']
    hjc_te=tr_ds[test_yr]['hjc_payout']
    raw_te=model.predict(X_te,raw_score=True)
    rd_te=defaultdict(list)
    for i,(rid,combo) in enumerate(meta_te): rd_te[rid].append(i)
    for rid2,idxs in rd_te.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
        probs=np.exp(s)/np.exp(s).sum()
        for j,idx in enumerate(idxs):
            ev=probs[j]*odds_te[idx]
            all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(y_te[idx]),
                             'payout':float(hjc_te[idx]),'odds':odds_te[idx],
                             'pop':int(pop_te[idx]),'rid':rid2,'month':month_te[idx],
                             'mdl_p':float(probs[j]),'combo':meta_te[idx][1]})

print(f"\nTotal bets: {len(all_bets):,}")
BET=100

# === 詳細分析 ===
print(f"\n{'='*90}")
print("v21b: 三連複 SH基準 詳細分析")
print(f"{'='*90}")

# 1. EV閾値×人気フィルタ
print(f"\n--- 1. EV閾値 × 人気フィルタ ---")
print(f"{'フィルタ':>14} {'EV>=':>5} {'n':>7} {'的中':>5} {'的中率':>6} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"{'-'*82}")
for pop_label,pop_max in [('1番人気含む',1),('1-3番人気含む',3),('全組合せ',99)]:
    for ev_th in [0.8,1.0,1.1,1.2,1.3,1.5,2.0]:
        sub=[d for d in all_bets if d['ev']>=ev_th and d['pop']<=pop_max]
        if not sub or len(sub)<10: continue
        n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
        inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: parts.append(''); continue
            yi=len(ys)*BET; yp=sum(d['payout']*BET for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:.1f}%")
        print(f"{pop_label:>14} {ev_th:>4.1f} {n:>7} {hits:>5} {hr:>5.2%} {rec:>6.1f}% | {' '.join(parts)}")

# 2. レース単位（1番人気含む EV>=1.2）
print(f"\n--- 2. レース単位収支（1番人気含む × EV>=1.2）---")
by_race=defaultdict(lambda:{'inv':0,'pay':0,'n_bets':0,'has_hit':False,'year':0,'month':''})
for d in all_bets:
    if d['ev']<1.2 or d['pop']>1: continue
    r=by_race[d['rid']]
    r['inv']+=BET; r['pay']+=d['payout']*BET if d['is_hit'] else 0
    r['n_bets']+=1; r['has_hit']=r['has_hit'] or d['is_hit']
    r['year']=d['year']; r['month']=d['month']
races=list(by_race.values())
if races:
    pnls=[r['pay']-r['inv'] for r in races]
    hit_r=sum(1 for r in races if r['has_hit'])
    print(f"  参加R={len(races)} 的中R={hit_r} ({hit_r/len(races):.1%})")
    print(f"  平均点数/R={np.mean([r['n_bets'] for r in races]):.1f} 平均投資/R={np.mean([r['inv'] for r in races]):.0f}円")
    print(f"  収支: mean={np.mean(pnls):.0f}円 median={np.median(pnls):.0f}円")
    for pct in [10,25,50,75,90,95,99]:
        print(f"    {pct}%ile: {np.percentile(pnls,pct):.0f}円")
    # 点数分布
    bets_per_race=[r['n_bets'] for r in races]
    print(f"\n  点数/R分布:")
    for nb in sorted(set(bets_per_race)):
        cnt=bets_per_race.count(nb)
        if cnt>=10:
            sub_r=[r for r in races if r['n_bets']==nb]
            rec_r=sum(r['pay'] for r in sub_r)/sum(r['inv'] for r in sub_r)*100
            print(f"    {nb}点: {cnt}R ({cnt/len(races):.1%}) 回収率={rec_r:.1f}%")

# 3. 推定オッズ帯別（1番人気含む EV>=1.2）
print(f"\n--- 3. 推定オッズ帯別（1番人気含む × EV>=1.2）---")
for lo,hi in [(0,20),(20,50),(50,100),(100,200),(200,500),(500,9999)]:
    sub=[d for d in all_bets if d['ev']>=1.2 and d['pop']<=1 and lo<=d['odds']<hi]
    if len(sub)<10: continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
    inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
    label=f"{lo}-{hi}" if hi<9999 else f"{lo}+"
    print(f"  {label:>8}x: n={n:,} 的中={hits} ({hr:.2%}) rec={rec:.1f}% avg_payout={pay/max(hits,1)/BET:.1f}倍")

# 4. 1年50%ルール（1番人気含む EV>=1.2）
print(f"\n--- 4. 1年50%ルール（1番人気含む × EV>=1.2）---")
sub=[d for d in all_bets if d['ev']>=1.2 and d['pop']<=1]
total_inv=len(sub)*BET; total_pay=sum(d['payout']*BET for d in sub if d['is_hit']); total_pnl=total_pay-total_inv
print(f"  total PnL={total_pnl:+,.0f}円")
for yr in [2024,2025,2026]:
    ys=[d for d in sub if d['year']==yr]
    if not ys: continue
    n=len(ys); inv=n*BET; pay=sum(d['payout']*BET for d in ys if d['is_hit'])
    pnl=pay-inv; pnl_pct=pnl/abs(total_pnl)*100 if total_pnl!=0 else 0
    flag="*** 50%超 ***" if abs(pnl_pct)>50 else ""
    print(f"  {yr}: n={n:,} PnL={pnl:+,.0f}円 ({pnl_pct:+.0f}%) rec={pay/inv*100:.1f}% {flag}")

# 5. 月別累積（1番人気含む EV>=1.2）
print(f"\n--- 5. 月別累積損益（1番人気含む × EV>=1.2）---")
months=sorted(set(d['month'] for d in sub if d['month']))
cum_pnl=0
print(f"  {'月':>7} {'n':>5} {'的中':>4} {'投資':>8} {'払戻':>8} {'月PnL':>8} {'累積PnL':>9}")
for m in months:
    ms=[d for d in sub if d['month']==m]
    n=len(ms); hits=sum(d['is_hit'] for d in ms)
    inv=n*BET; pay=sum(d['payout']*BET for d in ms if d['is_hit'])
    pnl=pay-inv; cum_pnl+=pnl
    print(f"  {m:>7} {n:>5} {hits:>4} {inv:>7,} {pay:>7,.0f} {pnl:>+7,.0f} {cum_pnl:>+8,.0f}")

# 6. キャリブレーション
print(f"\n--- 6. EV帯別キャリブレーション（1番人気含む）---")
print(f"  {'EV帯':>10} {'n':>7} {'予測P':>8} {'実績P':>8} {'比':>5} {'回収率':>7}")
for lo,hi in [(0.5,0.8),(0.8,1.0),(1.0,1.2),(1.2,1.5),(1.5,2.0),(2.0,3.0),(3.0,99)]:
    sub2=[d for d in all_bets if lo<=d['ev']<hi and d['pop']<=1]
    if len(sub2)<10: continue
    n=len(sub2); avg_p=np.mean([d['mdl_p'] for d in sub2]); avg_hit=np.mean([d['is_hit'] for d in sub2])
    ratio=avg_hit/avg_p if avg_p>0 else 0
    inv=n*BET; pay=sum(d['payout']*BET for d in sub2 if d['is_hit']); rec=pay/inv*100
    label=f"{lo:.1f}-{hi:.1f}" if hi<99 else f"{lo:.1f}+"
    print(f"  {label:>10} {n:>7} {avg_p:>7.5f} {avg_hit:>7.5f} {ratio:>4.2f} {rec:>6.1f}%")

# 7. ブートストラップCI
print(f"\n--- 7. ブートストラップCI ---")
for pop_label,pop_max in [('1番人気含む',1),('全組合せ',99)]:
    for ev_th in [1.0,1.2,1.5]:
        sub3=[d for d in all_bets if d['ev']>=ev_th and d['pop']<=pop_max]
        if len(sub3)<100: continue
        by_r=defaultdict(list)
        for d in sub3: by_r[d['rid']].append(d)
        rids=list(by_r.keys()); np.random.seed(42); br=[]
        for _ in range(5000):
            samp=np.random.choice(rids,size=len(rids),replace=True)
            si=0; sp=0
            for r in samp:
                for d in by_r[r]: si+=BET; sp+=d['payout']*BET if d['is_hit'] else 0
            if si>0: br.append(sp/si*100)
        br.sort()
        inv=len(sub3)*BET; pay=sum(d['payout']*BET for d in sub3 if d['is_hit'])
        print(f"  {pop_label} EV>={ev_th}: n={len(sub3):,} rec={pay/inv*100:.1f}% CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

print("\nDone!")
