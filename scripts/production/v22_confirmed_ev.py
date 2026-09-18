# -*- coding: utf-8 -*-
"""v22: Fable指示 — confirmed_oddsでEV判定+回収率（分母統一）
推定オッズを使わず、確定オッズで統一。
EV = P_model × O_確定
回収率 = HJC確定オッズ（= O_確定と同一）

審査ルール追加: 「推定オッズを分母にしたEVの回収率は報告しない」

追加出力:
- 上位5的中除外後の回収率
- 選択後キャリブレーション（P_model平均 vs 実測的中率）
- 1番人気フィルタなしの結果
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
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}

def sh_all(p):
    n=len(p); p2=p**LAM2; p3=p**LAM3
    S1=p.sum(); S2=p2.sum(); S3=p3.sum()
    umaren=defaultdict(float); trio=defaultdict(float)
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
                trio[tuple(sorted([i,j,k]))]+=pij*(p3[k]/d3)
    return umaren, trio

# データセット構築
print("Building datasets...", flush=True)
js={}; hh={}; ts_st={}
# 券種: umaren, sanrenpuku（順序なし券種のみ。馬単・三連単は順序問題があるので後回し）
bet_types = ['umaren', 'sanrenpuku']
ds = {bt:{} for bt in bet_types}
FNAMES = {bt:None for bt in bet_types}

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
    fps=result_full.get(rid,{})
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    rank_map={h:i+1 for i,(h,o) in enumerate(sorted_h)}

    # SH基準の市場確率（init_scoreに使う）
    umaren_sh, trio_sh = sh_all(mp)

    # 馬ごと特徴量
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

    # confirmed_odds取得
    co = defaultdict(dict)
    for row in cdb.execute("SELECT bet_type,combination,odds FROM confirmed_odds WHERE race_id=? AND odds>0 AND bet_type IN ('umaren','sanrenpuku')", (rid,)).fetchall():
        co[row[0]][row[1]] = row[2]

    top8=[h for h,_ in sorted_h[:8]] if sorted_h else hl[:8]

    # --- 馬連 ---
    top2_fps=sorted([r for r in rl if r['fp'] in (1,2)],key=lambda x:x['fp'])
    if len(top2_fps)>=2 and co.get('umaren'):
        winner_um='-'.join(str(x) for x in sorted([top2_fps[0]['hn'],top2_fps[1]['hn']]))
        if year not in ds['umaren']:
            ds['umaren'][year]={'X':[],'y':[],'init':[],'meta':[],'co_odds':[],'pop':[]}
        for a,b in combinations(top8,2):
            ai=hl.index(a); bi=hl.index(b)
            key=tuple(sorted([ai,bi]))
            sh_p=umaren_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b]))
            confirmed_o=co['umaren'].get(combo,0)
            if confirmed_o<=0: continue
            pf={}
            f1=feats_h[a]; f2=feats_h[b]
            for k in FEAT_KEYS:
                pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0); pf[f'{k}_diff']=abs(f1.get(k,0)-f2.get(k,0))
            ow1=f1.get('win_odds_3min',0); ow2=f2.get('win_odds_3min',0)
            pf['win_odds_ratio']=min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
            pf['win_odds_sum_inv']=(1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
            if FNAMES['umaren'] is None: FNAMES['umaren']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_um else 0
            pop=min(rank_map.get(a,99),rank_map.get(b,99))
            ds['umaren'][year]['X'].append([pf.get(k,0) for k in FNAMES['umaren']])
            ds['umaren'][year]['y'].append(is_hit)
            ds['umaren'][year]['init'].append(init)
            ds['umaren'][year]['meta'].append((rid,combo))
            ds['umaren'][year]['co_odds'].append(confirmed_o)
            ds['umaren'][year]['pop'].append(pop)

    # --- 三連複 ---
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])
    if len(top3_fps)>=3 and co.get('sanrenpuku'):
        winner_tr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in ds['sanrenpuku']:
            ds['sanrenpuku'][year]={'X':[],'y':[],'init':[],'meta':[],'co_odds':[],'pop':[]}
        for a,b,c in combinations(top8,3):
            ai=hl.index(a); bi=hl.index(b); ci=hl.index(c)
            key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c]))
            confirmed_o=co['sanrenpuku'].get(combo,0)
            if confirmed_o<=0: continue
            pf={}
            f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
            for k in FEAT_KEYS:
                v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
            odds_list=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
            pf['win_odds_top_ratio']=odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
            pf['win_odds_sum_inv']=sum(1/o for o in odds_list if o>0)
            if FNAMES['sanrenpuku'] is None: FNAMES['sanrenpuku']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_tr else 0
            pop=min(rank_map.get(a,99),rank_map.get(b,99),rank_map.get(c,99))
            ds['sanrenpuku'][year]['X'].append([pf.get(k,0) for k in FNAMES['sanrenpuku']])
            ds['sanrenpuku'][year]['y'].append(is_hit)
            ds['sanrenpuku'][year]['init'].append(init)
            ds['sanrenpuku'][year]['meta'].append((rid,combo))
            ds['sanrenpuku'][year]['co_odds'].append(confirmed_o)
            ds['sanrenpuku'][year]['pop'].append(pop)
    do_update()
    n_proc+=1
    if n_proc%2000==0: print(f"  {n_proc}R...", flush=True)
cdb.close()

for bt in bet_types:
    for y in sorted(ds[bt].keys()):
        d=ds[bt][y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['co_odds']=np.array(d['co_odds'])
        d['pop']=np.array(d['pop'])
    sizes=', '.join(str(y)+':'+str(len(ds[bt][y]['X'])) for y in sorted(ds[bt].keys()))
    print(f"  {bt}: {sizes}")

# WF
lgb_params={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
            'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
            'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

def run_wf(bt_ds, fnames, label, hjc_type):
    print(f"\n--- {label} ---")
    all_bets=[]
    for test_yr in [2024,2025,2026]:
        train_yrs=[y for y in range(2022,test_yr) if y in bt_ds]; fit_yr=test_yr-1
        if not train_yrs or fit_yr not in bt_ds or test_yr not in bt_ds: continue
        X_tr=np.vstack([bt_ds[y]['X'] for y in train_yrs])
        y_tr=np.concatenate([bt_ds[y]['y'] for y in train_yrs])
        init_tr=np.concatenate([bt_ds[y]['init'] for y in train_yrs])
        model=lgb.train(lgb_params,lgb.Dataset(X_tr,y_tr,feature_name=fnames,init_score=init_tr),num_boost_round=300)
        X_f=bt_ds[fit_yr]['X']; y_f=bt_ds[fit_yr]['y']; init_f=bt_ds[fit_yr]['init']
        raw_f=model.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,(rid,combo) in enumerate(bt_ds[fit_yr]['meta']): rd_f[rid].append(i)
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
        X_te=bt_ds[test_yr]['X']; y_te=bt_ds[test_yr]['y']; init_te=bt_ds[test_yr]['init']
        meta_te=bt_ds[test_yr]['meta']; co_odds_te=bt_ds[test_yr]['co_odds']
        pop_te=bt_ds[test_yr]['pop']
        raw_te=model.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,(rid,combo) in enumerate(meta_te): rd_te[rid].append(i)
        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_use*init_te[idxs]+tau_use*raw_te[idxs]; s-=s.max()
            probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                # EV = P_model × O_確定
                ev=probs[j]*co_odds_te[idx]
                is_hit=y_te[idx]
                # 払戻も同じ確定オッズ
                payout=co_odds_te[idx] if is_hit else 0
                all_bets.append({'year':test_yr,'ev':float(ev),'is_hit':int(is_hit),
                                 'payout':float(payout),'co_odds':float(co_odds_te[idx]),
                                 'pop':int(pop_te[idx]),'rid':rid2,
                                 'mdl_p':float(probs[j]),'combo':meta_te[idx][1]})
    return all_bets

print("\nWF...", flush=True)
bets_um = run_wf(ds['umaren'], FNAMES['umaren'], '馬連', 'umaren_hjc')
bets_tr = run_wf(ds['sanrenpuku'], FNAMES['sanrenpuku'], '三連複', 'sanrenpuku_hjc')

# === Fable指示の出力 ===
BET=100
print(f"\n{'='*90}")
print("v22: confirmed_oddsでEV判定+回収率（Fable指示、分母統一）")
print(f"{'='*90}")

for bt_label, data in [('馬連', bets_um), ('三連複', bets_tr)]:
    print(f"\n■ {bt_label}")
    # EV閾値別（フィルタなし + 1番人気含む）
    print(f"  {'フィルタ':>14} {'EV>=':>5} {'n':>7} {'的中':>5} {'的中率':>7} {'回収率':>7} | {'2024':>7} {'2025':>7} {'2026':>7}")
    print(f"  {'-'*82}")
    for pop_label, pop_max in [('全組合せ',99),('1番人気含む',1)]:
        for ev_th in [0.8, 1.0, 1.1, 1.2, 1.3, 1.5]:
            sub=[d for d in data if d['ev']>=ev_th and d['pop']<=pop_max]
            if not sub or len(sub)<10: continue
            n=len(sub); hits=sum(d['is_hit'] for d in sub); hr=hits/n
            inv=n*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit']); rec=pay/inv*100
            parts=[]
            for yr in [2024,2025,2026]:
                ys=[d for d in sub if d['year']==yr]
                if not ys: parts.append(''); continue
                yi=len(ys)*BET; yp=sum(d['payout']*BET for d in ys if d['is_hit'])
                parts.append(f"{yp/yi*100:.1f}%")
            print(f"  {pop_label:>14} {ev_th:>4.1f} {n:>7} {hits:>5} {hr:>6.2%} {rec:>6.1f}% | {' '.join(parts)}")

    # キャリブレーション（EV>=1.0）
    print(f"\n  --- キャリブレーション（P_model vs 実測的中率）---")
    for ev_th in [1.0, 1.2]:
        sub=[d for d in data if d['ev']>=ev_th]
        if len(sub)<10: continue
        avg_p=np.mean([d['mdl_p'] for d in sub])
        avg_hit=np.mean([d['is_hit'] for d in sub])
        ratio=avg_hit/avg_p if avg_p>0 else 0
        print(f"  EV>={ev_th}: avg_P={avg_p:.5f} 実測={avg_hit:.5f} 比={ratio:.2f}")

    # 上位5的中除外後の回収率（EV>=1.2）
    sub12=[d for d in data if d['ev']>=1.2]
    if sub12:
        hits_sorted=sorted([d for d in sub12 if d['is_hit']], key=lambda x:-x['payout'])
        inv_all=len(sub12)*BET
        pay_all=sum(d['payout']*BET for d in sub12 if d['is_hit'])
        pay_ex5=pay_all-sum(d['payout']*BET for d in hits_sorted[:5])
        rec_all=pay_all/inv_all*100; rec_ex5=pay_ex5/inv_all*100
        print(f"\n  EV>=1.2: 回収率={rec_all:.1f}% | 上位5的中除外={rec_ex5:.1f}%")

    # ブートストラップCI
    for ev_th in [1.0, 1.2]:
        sub=[d for d in data if d['ev']>=ev_th]
        if len(sub)<100: continue
        by_race=defaultdict(list)
        for d in sub: by_race[d['rid']].append(d)
        rids=list(by_race.keys()); np.random.seed(42); br=[]
        for _ in range(5000):
            samp=np.random.choice(rids,size=len(rids),replace=True)
            si=0; sp=0
            for r in samp:
                for d in by_race[r]: si+=BET; sp+=d['payout']*BET if d['is_hit'] else 0
            if si>0: br.append(sp/si*100)
        br.sort()
        inv=len(sub)*BET; pay=sum(d['payout']*BET for d in sub if d['is_hit'])
        print(f"  CI EV>={ev_th}: n={len(sub):,} rec={pay/inv*100:.1f}% 95%CI=[{br[int(.025*len(br))]:.1f}%, {br[int(.975*len(br))]:.1f}%]")

print("\nDone!")
