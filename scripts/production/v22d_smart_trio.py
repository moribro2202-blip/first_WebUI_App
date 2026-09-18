# -*- coding: utf-8 -*-
"""v22d: スマート三連 — 1レースごとに三連単or三連複を選択
モデルtop1の勝率が35%以上 → 三連単（1着固定流し）
モデルtop1の勝率が35%未満 → 三連複

三連単: top1を1着固定、top2-8から2頭選んでC(7,2)=21組 × 2通り(2-3着入替) = 42通り
三連複: top8からC(8,3)=56組

EV判定: P_model × O_確定（v22方式）
払戻: O_確定
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

LAM2, LAM3 = 0.8076, 0.6978
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']

def sh_all(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    trio=defaultdict(float); trifecta=defaultdict(float)
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
                pijk=pij*(p3[k]/d3)
                trio[tuple(sorted([i,j,k]))]+=pijk
                trifecta[(i,j,k)]=pijk
    return trio, trifecta

# 単勝モデル構築（勝率予測用）
print("Building win model...", flush=True)
js={}; hh={}; ts_st={}; win_ds={}; WFNAMES=None
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
    if year not in win_ds: win_ds[year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
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
    tc=race_cond.get(rid,'良'); grade=race_grade.get(rid) or '一般'
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
        cw=ent.get('weight') or 0; avg_cw=np.mean([entries.get(h2,{}).get('weight') or 0 for h2 in hl])
        f['weight_c']=(cw-avg_cw) if cw>0 else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        if WFNAMES is None: WFNAMES=sorted(f.keys())
        win_ds[year]['X'].append([f.get(k,0) for k in WFNAMES])
        win_ds[year]['y'].append(1 if h==winners[0] else 0)
        win_ds[year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        win_ds[year]['meta'].append((rid,h))
        win_ds[year]['odds'].append(o3.get(h,0))
    do_update()
for y in win_ds:
    d=win_ds[y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
    d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])

lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

# WF: 単勝モデルで勝率予測 → レースごとに三連単or三連複を選択
print("\nWF + Smart Trio...", flush=True)
BET = 100
# 3戦略: 三連複のみ / 三連単のみ / スマート（切替）
strats = {'三連複のみ':[], '三連単のみ':[], 'スマート':[], '単勝(参考)':[]}

cdb = sqlite3.connect(DB, timeout=30)
for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr) if y in win_ds]; fit_yr=test_yr-1
    if not train_yrs or fit_yr not in win_ds or test_yr not in win_ds: continue
    X_tr=np.vstack([win_ds[y]['X'] for y in train_yrs])
    y_tr=np.concatenate([win_ds[y]['y'] for y in train_yrs])
    init_tr=np.concatenate([win_ds[y]['init'] for y in train_yrs])
    model=lgb.train(lgb_w,lgb.Dataset(X_tr,y_tr,feature_name=WFNAMES,init_score=init_tr),num_boost_round=300)
    X_f=win_ds[fit_yr]['X']; y_f=win_ds[fit_yr]['y']; init_f=win_ds[fit_yr]['init']
    raw_f=model.predict(X_f,raw_score=True)
    rd_f=defaultdict(list)
    for i,(rid,hn) in enumerate(win_ds[fit_yr]['meta']): rd_f[rid].append(i)
    def neg_ll(p):
        b,tau=p; nll=0; nr=0
        for rid2,idxs in rd_f.items():
            ys=y_f[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b*init_f[idxs]+tau*raw_f[idxs]; s-=s.max()
            nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
        return nll/nr if nr>0 else 999
    res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
    bw,tw=res.x; print(f"  {test_yr}: b={bw:.3f} tau={tw:.3f}")

    X_te=win_ds[test_yr]['X']; y_te=win_ds[test_yr]['y']; init_te=win_ds[test_yr]['init']
    meta_te=win_ds[test_yr]['meta']; odds_te=win_ds[test_yr]['odds']
    raw_te=model.predict(X_te,raw_score=True)
    rd_te=defaultdict(list)
    for i,(rid,hn) in enumerate(meta_te): rd_te[rid].append(i)

    for rid2,idxs in rd_te.items():
        ys=y_te[idxs]; wi=np.where(ys==1)[0]
        if len(wi)==0: continue
        s=bw*init_te[idxs]+tw*raw_te[idxs]; s-=s.max()
        probs=np.exp(s)/np.exp(s).sum()
        hns=[meta_te[idx][1] for idx in idxs]
        fps=result_full.get(rid2,{})
        hjc=hjc_all.get(rid2,{})
        hl=race_horses.get(rid2,[])
        month=race_dates.get(rid2,'')[:7]

        # SH確率
        trio_sh, trifecta_sh = sh_all(probs)

        # top1の勝率
        top1_idx=np.argmax(probs)
        top1_p=probs[top1_idx]
        top1_hn=hns[top1_idx]
        use_trifecta = (top1_p >= 0.35)

        # confirmed_odds
        co_tr = {}; co_st = {}
        for row in cdb.execute("SELECT bet_type,combination,odds FROM confirmed_odds WHERE race_id=? AND odds>0 AND bet_type IN ('sanrenpuku','sanrentan')", (rid2,)).fetchall():
            if row[0]=='sanrenpuku': co_tr[row[1]]=row[2]
            else: co_st[row[1]]=row[2]

        sorted_h=sorted([(hns[j],probs[j]) for j in range(len(hns))],key=lambda x:-x[1])
        top8_hns=[h for h,_ in sorted_h[:8]]

        # 1-2-3着
        top3_fps=sorted([r for r in result_cache.get(rid2,[]) if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
        if len(top3_fps)<3: continue
        winner_tr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        winner_st=f"{top3_fps[0]['hn']}-{top3_fps[1]['hn']}-{top3_fps[2]['hn']}"

        # --- 三連複 ---
        for a,b,c in combinations(top8_hns,3):
            combo='-'.join(str(x) for x in sorted([a,b,c]))
            co=co_tr.get(combo,0)
            if co<=0: continue
            ai=hns.index(a); bi=hns.index(b); ci=hns.index(c)
            key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_sh.get(key,0)
            if sh_p<=0: continue
            ev=sh_p*co
            is_hit=1 if combo==winner_tr else 0
            payout=co if is_hit else 0
            bet={'year':test_yr,'ev':float(ev),'is_hit':is_hit,'payout':payout,'rid':rid2,'month':month,'type':'trio'}
            strats['三連複のみ'].append(bet)
            if not use_trifecta:
                strats['スマート'].append(bet)

        # --- 三連単（top1固定流し）---
        if co_st:
            other7=[h for h in top8_hns if h!=top1_hn][:7]
            for b_h,c_h in permutations(other7,2):
                combo=f"{top1_hn}-{b_h}-{c_h}"
                co=co_st.get(combo,0)
                if co<=0: continue
                ai=hns.index(top1_hn); bi=hns.index(b_h); ci=hns.index(c_h)
                sh_p=trifecta_sh.get((ai,bi,ci),0)
                if sh_p<=0: continue
                ev=sh_p*co
                is_hit=1 if combo==winner_st else 0
                payout=co if is_hit else 0
                bet={'year':test_yr,'ev':float(ev),'is_hit':is_hit,'payout':payout,'rid':rid2,'month':month,'type':'trifecta'}
                strats['三連単のみ'].append(bet)
                if use_trifecta:
                    strats['スマート'].append(bet)

        # --- 単勝（参考）---
        for j in range(len(hns)):
            o=odds_te[idxs[j]]
            if not(2<=o<=40): continue
            ev=probs[j]*o
            is_hit=int(hns[j]==top3_fps[0]['hn'])
            payout=hjc.get('win_hjc',{}).get(str(hns[j]),0) if is_hit else 0
            strats['単勝(参考)'].append({'year':test_yr,'ev':float(ev),'is_hit':is_hit,'payout':payout,'rid':rid2,'month':month,'type':'win'})

cdb.close()

# === 結果 ===
print(f"\n{'='*90}")
print("v22d: スマート三連（1レースごとに三連単or三連複を選択）")
print(f"  条件: モデルtop1確率>=35% → 三連単（1着固定流し）/ それ以外 → 三連複")
print(f"{'='*90}")

print(f"\n{'戦略':>12} {'EV>=':>5} {'n':>7} {'的中':>5} {'的中率':>7} {'回収率':>7} {'R':>6} {'点/R':>5} | {'2024':>7} {'2025':>7} {'2026':>7}")
print(f"{'-'*90}")
for strat_name in ['単勝(参考)','三連複のみ','三連単のみ','スマート']:
    data=strats[strat_name]
    if not data: continue
    for ev_th in [1.0, 1.2, 1.5]:
        sub=[d for d in data if d['ev']>=ev_th]
        if not sub or len(sub)<10: continue
        n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
        inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
        n_races=len(set(d['rid'] for d in sub)); pts_r=n/max(n_races,1)
        parts=[]
        for yr in [2024,2025,2026]:
            ys=[d for d in sub if d['year']==yr]
            if not ys: parts.append(''); continue
            yi=len(ys)*BET; yp=sum(d['payout']*BET for d in ys if d['is_hit'])
            parts.append(f"{yp/yi*100:.1f}%")
        print(f"{strat_name:>12} {ev_th:>4.1f} {n:>7} {hits:>5} {hr:>6.2%} {rec:>6.1f}% {n_races:>6} {pts_r:>4.1f} | {' '.join(parts)}")

# 年間PnL比較（1R=1000円）
print(f"\n--- 年間PnL比較（1R=1000円投資）---")
for strat_name in ['単勝(参考)','三連複のみ','三連単のみ','スマート']:
    data=strats[strat_name]
    for ev_th in [1.2]:
        sub=[d for d in data if d['ev']>=ev_th]
        if not sub or len(sub)<10: continue
        n=len(sub); n_races=len(set(d['rid'] for d in sub)); pts_r=n/max(n_races,1)
        inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
        r_per_year=n_races/3; annual_inv=r_per_year*1000; annual_pnl=annual_inv*(rec/100-1)
        print(f"  {strat_name:>12} EV>=1.2: {n_races}R ({r_per_year:.0f}/年) {pts_r:.1f}点/R rec={rec:.1f}% 年間PnL={annual_pnl:+,.0f}円")

# スマート戦略の内訳
print(f"\n--- スマート戦略の内訳（EV>=1.2）---")
smart12=[d for d in strats['スマート'] if d['ev']>=1.2]
trio_part=[d for d in smart12 if d['type']=='trio']
tri_part=[d for d in smart12 if d['type']=='trifecta']
for label, sub in [('三連複部分',trio_part),('三連単部分',tri_part)]:
    if not sub: continue
    n=len(sub); hits=sum(d['is_hit'] for d in sub)
    inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
    n_races=len(set(d['rid'] for d in sub))
    print(f"  {label}: n={n:,} ({n_races}R) 的中={hits} rec={rec:.1f}%")

print("\nDone!")
