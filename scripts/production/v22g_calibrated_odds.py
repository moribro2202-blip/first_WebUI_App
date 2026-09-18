# -*- coding: utf-8 -*-
"""v22g: 推定オッズをオッズ帯別に補正して全券種シミュレーション
前年の「SH推定オッズ vs 確定オッズ」比率テーブルでキャリブレーション
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
TAKEOUT = {'win':0.20,'umaren':0.225,'sanrenpuku':0.25,'sanrentan':0.2725}
FEAT_KEYS = ['idm_c','rider_c','total_index','expert_resid','cyb_c',
             'jockey_t3rate','trainer_t3rate','horse_runs','avg_fp_5',
             'top3_rate','last_fp','win_rate','is_senkou','move_5to3']
grade_map = {'G1':6,'G2':5,'G3':4,'OP':3,'L':2,'3勝':1,'2勝':0,'1勝':-1,'未勝利':-2,'新馬':-3,'一般':0}
tc_map = {'良':0,'稍重':1,'重':2,'不良':3}; sf_map = {'芝':0,'ダート':1}
BT_JP={'win':'単勝','umaren':'馬連','trio':'三連複','trifecta':'三連単'}

# ============================================================
# Step 1: オッズ帯別補正テーブルの構築（前年フィット）
# ============================================================
def build_odds_calibration(year_data, bt_type):
    """SH推定オッズと確定オッズの比率をオッズ帯別に計算
    Returns: list of (lo, hi, median_ratio) — 推定オッズ帯で分類
    """
    ratios_by_band = defaultdict(list)
    for est_o, conf_o in year_data:
        if est_o <= 0 or conf_o <= 0: continue
        ratio = conf_o / est_o
        # 推定オッズ帯（判定時に使う値で分類）
        if est_o < 10: band = (0, 10)
        elif est_o < 30: band = (10, 30)
        elif est_o < 100: band = (30, 100)
        elif est_o < 300: band = (100, 300)
        elif est_o < 1000: band = (300, 1000)
        else: band = (1000, 99999)
        ratios_by_band[band].append(ratio)

    cal_table = []
    for band in sorted(ratios_by_band.keys()):
        vals = ratios_by_band[band]
        if len(vals) >= 20:
            cal_table.append((band[0], band[1], float(np.median(vals))))
    return cal_table

def apply_calibration(est_odds, cal_table):
    """推定オッズに補正テーブルを適用"""
    for lo, hi, ratio in cal_table:
        if lo <= est_odds < hi:
            return est_odds * ratio
    # テーブルにない帯はそのまま
    return est_odds

# ============================================================
# Step 2: データセット構築 + 補正テーブル用データ収集
# ============================================================
print("Building datasets + calibration data...", flush=True)
js={}; hh={}; ts_st={}
ds = {'win':{},'umaren':{},'trio':{},'trifecta':{}}
FNAMES = {'win':None,'umaren':None,'trio':None,'trifecta':None}
# 補正テーブル用: {year: {bt: [(est_odds, conf_odds), ...]}}
cal_data = defaultdict(lambda: defaultdict(list))

cdb = sqlite3.connect(DB, timeout=30)
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
    fps=result_full.get(rid,{})
    p2=mp**LAM2; p3=mp**LAM3; S1=mp.sum(); S2=p2.sum(); S3=p3.sum()
    umaren_sh=defaultdict(float); trio_sh=defaultdict(float); trifecta_sh={}
    for i in range(n):
        d2=S2-p2[i]
        if d2<=0: continue
        for j in range(n):
            if j==i: continue
            pij=(mp[i]/S1)*(p2[j]/d2); umaren_sh[tuple(sorted([i,j]))]+=pij
            d3=S3-p3[i]-p3[j]
            if d3<=0: continue
            for k in range(n):
                if k in (i,j): continue
                pijk=pij*(p3[k]/d3)
                trio_sh[tuple(sorted([i,j,k]))]+=pijk; trifecta_sh[(i,j,k)]=pijk
    sorted_h=sorted(odds_mkt.items(),key=lambda x:x[1])
    top8=[h for h,_ in sorted_h[:8]]
    top1_idx=np.argmax(mp); top1_hn=hl[top1_idx]; top1_p=mp[top1_idx]
    feats_h={}
    for i,h in enumerate(hl):
        ent=entries.get(h,{}); hid=ent.get('hid',''); f={}
        f['idm_c']=(ent.get('idm') or 50)-avg_idm; f['rider_c']=(ent.get('rider') or 0)-avg_rider
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
        else: f.update({'avg_fp_5':8,'top3_rate':0,'last_fp':8,'win_rate':-1})
        f['is_senkou']=1 if ent.get('run_style','') in ('逃げ','先行') else 0
        if has_move:
            oo5=o5.get(h,0); oo3=o3.get(h,0)
            f['move_5to3']=(oo5-oo3)/oo5 if oo5>0 and oo3>0 else 0
        else: f['move_5to3']=0
        f['win_odds_3min']=o3.get(h,0); feats_h[h]=f

    # 単勝
    if year not in ds['win']: ds['win'][year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
    if FNAMES['win'] is None: FNAMES['win']=sorted(FEAT_KEYS)
    for i,h in enumerate(hl):
        ds['win'][year]['X'].append([feats_h[h].get(k,0) for k in FNAMES['win']])
        ds['win'][year]['y'].append(1 if h==winners[0] else 0)
        ds['win'][year]['init'].append(math.log(max(mp[i],1e-15))-math.log(max(1-mp[i],1e-15)))
        ds['win'][year]['meta'].append((rid,h)); ds['win'][year]['odds'].append(o3.get(h,0))

    top2_fps=sorted([r for r in rl if r['fp'] in (1,2)],key=lambda x:x['fp'])
    top3_fps=sorted([r for r in rl if r['fp'] in (1,2,3)],key=lambda x:x['fp'])

    # confirmed_odds取得（補正テーブル用）
    co_um={}; co_tr={}; co_st={}
    for row in cdb.execute("SELECT bet_type,combination,odds FROM confirmed_odds WHERE race_id=? AND odds>0 AND bet_type IN ('umaren','sanrenpuku','sanrentan')",(rid,)).fetchall():
        if row[0]=='umaren': co_um[row[1]]=row[2]
        elif row[0]=='sanrenpuku': co_tr[row[1]]=row[2]
        elif row[0]=='sanrentan': co_st[row[1]]=row[2]

    # 馬連
    if len(top2_fps)>=2:
        winner_um='-'.join(str(x) for x in sorted([top2_fps[0]['hn'],top2_fps[1]['hn']]))
        if year not in ds['umaren']: ds['umaren'][year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
        for a,b in combinations(top8,2):
            ai=hl.index(a); bi=hl.index(b); key=tuple(sorted([ai,bi]))
            sh_p=umaren_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b]))
            est_o=(1/sh_p)*(1-TAKEOUT['umaren'])
            conf_o=co_um.get(combo,0)
            if conf_o>0: cal_data[year]['umaren'].append((est_o, conf_o))
            pf={}; f1=feats_h[a]; f2=feats_h[b]
            for k in FEAT_KEYS: pf[f'{k}_sum']=f1.get(k,0)+f2.get(k,0); pf[f'{k}_diff']=abs(f1.get(k,0)-f2.get(k,0))
            ow1=f1.get('win_odds_3min',0); ow2=f2.get('win_odds_3min',0)
            pf['win_odds_ratio']=min(ow1,ow2)/max(ow1,ow2) if ow1>0 and ow2>0 else 0
            pf['win_odds_sum_inv']=(1/ow1+1/ow2) if ow1>0 and ow2>0 else 0
            if FNAMES['umaren'] is None: FNAMES['umaren']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_um else 0
            ds['umaren'][year]['X'].append([pf.get(k,0) for k in FNAMES['umaren']])
            ds['umaren'][year]['y'].append(is_hit); ds['umaren'][year]['init'].append(init)
            ds['umaren'][year]['meta'].append((rid,combo)); ds['umaren'][year]['odds'].append(est_o)

    # 三連複
    if len(top3_fps)>=3:
        winner_tr='-'.join(str(x) for x in sorted([top3_fps[0]['hn'],top3_fps[1]['hn'],top3_fps[2]['hn']]))
        if year not in ds['trio']: ds['trio'][year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
        for a,b,c in combinations(top8,3):
            ai=hl.index(a); bi=hl.index(b); ci=hl.index(c); key=tuple(sorted([ai,bi,ci]))
            sh_p=trio_sh.get(key,0)
            if sh_p<=0: continue
            combo='-'.join(str(x) for x in sorted([a,b,c]))
            est_o=(1/sh_p)*(1-TAKEOUT['sanrenpuku'])
            conf_o=co_tr.get(combo,0)
            if conf_o>0: cal_data[year]['sanrenpuku'].append((est_o, conf_o))
            pf={}; f1=feats_h[a]; f2=feats_h[b]; f3=feats_h[c]
            for k in FEAT_KEYS:
                v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
            odds_list=sorted([f.get('win_odds_3min',0) for f in [f1,f2,f3] if f.get('win_odds_3min',0)>0])
            pf['win_odds_top_ratio']=odds_list[0]/odds_list[-1] if len(odds_list)>=2 and odds_list[-1]>0 else 0
            pf['win_odds_sum_inv']=sum(1/o for o in odds_list if o>0)
            if FNAMES['trio'] is None: FNAMES['trio']=sorted(pf.keys())
            init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
            is_hit=1 if combo==winner_tr else 0
            ds['trio'][year]['X'].append([pf.get(k,0) for k in FNAMES['trio']])
            ds['trio'][year]['y'].append(is_hit); ds['trio'][year]['init'].append(init)
            ds['trio'][year]['meta'].append((rid,combo)); ds['trio'][year]['odds'].append(est_o)

        # 三連単
        if top1_p>=0.35:
            winner_st=f"{top3_fps[0]['hn']}-{top3_fps[1]['hn']}-{top3_fps[2]['hn']}"
            if year not in ds['trifecta']: ds['trifecta'][year]={'X':[],'y':[],'init':[],'meta':[],'odds':[]}
            other7=[h for h in top8 if h!=top1_hn][:7]
            for b_h,c_h in permutations(other7,2):
                bi=hl.index(b_h); ci=hl.index(c_h)
                sh_p=trifecta_sh.get((top1_idx,bi,ci),0)
                if sh_p<=0: continue
                combo=f"{top1_hn}-{b_h}-{c_h}"
                est_o=(1/sh_p)*(1-TAKEOUT['sanrentan'])
                conf_o=co_st.get(combo,0)
                if conf_o>0: cal_data[year]['sanrentan'].append((est_o, conf_o))
                pf={}; f1=feats_h[top1_hn]; f2=feats_h[b_h]; f3=feats_h[c_h]
                for k in FEAT_KEYS:
                    v1=f1.get(k,0); v2=f2.get(k,0); v3=f3.get(k,0)
                    pf[f'{k}_sum']=v1+v2+v3; pf[f'{k}_spread']=max(v1,v2,v3)-min(v1,v2,v3)
                pf['first_odds']=f1.get('win_odds_3min',0)
                pf['second_odds']=f2.get('win_odds_3min',0)
                pf['third_odds']=f3.get('win_odds_3min',0)
                if FNAMES['trifecta'] is None: FNAMES['trifecta']=sorted(pf.keys())
                init=math.log(max(sh_p,1e-15))-math.log(max(1-sh_p,1e-15))
                is_hit=1 if combo==winner_st else 0
                ds['trifecta'][year]['X'].append([pf.get(k,0) for k in FNAMES['trifecta']])
                ds['trifecta'][year]['y'].append(is_hit); ds['trifecta'][year]['init'].append(init)
                ds['trifecta'][year]['meta'].append((rid,combo)); ds['trifecta'][year]['odds'].append(est_o)
    do_update()
cdb.close()

for bt in ds:
    for y in sorted(ds[bt].keys()):
        d=ds[bt][y]; d['X']=np.array(d['X'],dtype=np.float32); d['y']=np.array(d['y'])
        d['init']=np.array(d['init'],dtype=np.float64); d['odds']=np.array(d['odds'])
    sizes=', '.join(f"{y}:{len(ds[bt][y]['X']):,}" for y in sorted(ds[bt].keys()))
    print(f"  {bt}: {sizes}")

# 補正テーブル表示
print(f"\n--- 補正テーブル（前年フィット用）---")
for yr in sorted(cal_data.keys()):
    for bt in sorted(cal_data[yr].keys()):
        cal = build_odds_calibration(cal_data[yr][bt], bt)
        print(f"  {yr} {bt}: {[(f'{lo}-{hi}',f'{r:.3f}') for lo,hi,r in cal]}")

# ============================================================
# WF + 補正済みオッズでEV判定
# ============================================================
lgb_w={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':7,'min_data_in_leaf':2000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}
lgb_p={'objective':'binary','metric':'binary_logloss','learning_rate':0.01,
       'num_leaves':15,'min_data_in_leaf':5000,'feature_fraction':0.5,
       'bagging_fraction':0.7,'bagging_freq':5,'lambda_l2':50.0,'verbose':-1,'seed':42}

BUDGET=1000; EV_TH=1.2
print("\nWF with calibrated odds...", flush=True)

all_bets = []
for test_yr in [2024,2025,2026]:
    train_yrs=[y for y in range(2022,test_yr)]; fit_yr=test_yr-1

    # 補正テーブル: 前年までの全データで構築
    cal_tables = {}
    for bt_cal in ['umaren','sanrenpuku','sanrentan']:
        all_cal = []
        for y in range(2022, test_yr):
            all_cal.extend(cal_data.get(y,{}).get(bt_cal,[]))
        cal_tables[bt_cal] = build_odds_calibration(all_cal, bt_cal)

    print(f"\n  {test_yr} calibration tables:")
    for bt_cal in cal_tables:
        print(f"    {bt_cal}: {[(f'{lo}-{hi}',f'{r:.3f}') for lo,hi,r in cal_tables[bt_cal]]}")

    # モデル学習
    models={}; params_fitted={}
    for bt in ds:
        if fit_yr not in ds[bt] or test_yr not in ds[bt]: continue
        avail=[y for y in train_yrs if y in ds[bt]]
        if not avail: continue
        X_tr=np.vstack([ds[bt][y]['X'] for y in avail])
        y_tr=np.concatenate([ds[bt][y]['y'] for y in avail])
        init_tr=np.concatenate([ds[bt][y]['init'] for y in avail])
        p=lgb_w if bt=='win' else lgb_p
        m=lgb.train(p,lgb.Dataset(X_tr,y_tr,feature_name=FNAMES[bt],init_score=init_tr),num_boost_round=300)
        X_f=ds[bt][fit_yr]['X']; y_f=ds[bt][fit_yr]['y']; init_f=ds[bt][fit_yr]['init']
        raw_f=m.predict(X_f,raw_score=True)
        rd_f=defaultdict(list)
        for i,meta in enumerate(ds[bt][fit_yr]['meta']): rd_f[meta[0]].append(i)
        def neg_ll(p_,init_=init_f,raw_=raw_f,y_=y_f,rd_=rd_f):
            b,tau=p_; nll=0; nr=0
            for rid2,idxs in rd_.items():
                ys=y_[idxs]; wi=np.where(ys==1)[0]
                if len(wi)==0: continue
                s=b*init_[idxs]+tau*raw_[idxs]; s-=s.max()
                nll-=(s[wi[0]]-math.log(np.exp(s).sum())); nr+=1
            return nll/nr if nr>0 else 999
        res=minimize(neg_ll,x0=[1.0,1.0],method='Nelder-Mead',options={'maxiter':1000})
        models[bt]=m; params_fitted[bt]=res.x

    # テスト年: 補正済みオッズでEV判定
    bets_by_race = defaultdict(lambda: defaultdict(list))
    for bt in models:
        if test_yr not in ds[bt]: continue
        b_,t_=params_fitted[bt]; m_=models[bt]
        X_te=ds[bt][test_yr]['X']; y_te=ds[bt][test_yr]['y']; init_te=ds[bt][test_yr]['init']
        meta_te=ds[bt][test_yr]['meta']; odds_te=ds[bt][test_yr]['odds']
        raw_te=m_.predict(X_te,raw_score=True)
        rd_te=defaultdict(list)
        for i,meta in enumerate(meta_te): rd_te[meta[0]].append(i)

        bt_cal_key = {'umaren':'umaren','trio':'sanrenpuku','trifecta':'sanrentan'}.get(bt)
        cal_table = cal_tables.get(bt_cal_key, [])

        for rid2,idxs in rd_te.items():
            ys=y_te[idxs]; wi=np.where(ys==1)[0]
            if len(wi)==0: continue
            s=b_*init_te[idxs]+t_*raw_te[idxs]; s-=s.max()
            probs=np.exp(s)/np.exp(s).sum()
            for j,idx in enumerate(idxs):
                raw_est_odds = odds_te[idx]
                if bt == 'win':
                    cal_odds = raw_est_odds  # 単勝は実オッズ
                    if not(2<=cal_odds<=40): continue
                else:
                    cal_odds = apply_calibration(raw_est_odds, cal_table)
                ev = probs[j] * cal_odds
                if ev < EV_TH: continue
                combo=meta_te[idx][1]; is_hit=y_te[idx]
                hjc_key={'win':'win_hjc','umaren':'umaren_hjc','trio':'sanrenpuku_hjc','trifecta':'sanrentan_hjc'}[bt]
                payout=hjc_all.get(rid2,{}).get(hjc_key,{}).get(str(combo) if bt=='win' else combo,0) if is_hit else 0
                bets_by_race[rid2][bt].append({'ev':float(ev),'payout':float(payout),'is_hit':int(is_hit),
                                                'cal_odds':float(cal_odds),'raw_odds':float(raw_est_odds)})

    # レースごとに最良券種を選択
    for rid2, bt_bets in bets_by_race.items():
        best_bt=None; best_profit=-999; best_cands=[]
        for bt, cands in bt_bets.items():
            if not cands: continue
            nn=len(cands); per=max(100,(BUDGET//nn//100)*100)
            inv=nn*per; exp_pay=sum(c['ev']*per for c in cands)
            profit=exp_pay-inv
            if profit>best_profit:
                best_profit=profit; best_bt=bt; best_cands=cands
        if best_bt is None: continue
        nn=len(best_cands); per=max(100,(BUDGET//nn//100)*100)
        inv=nn*per; payout=sum(c['payout']*per for c in best_cands if c['is_hit'])
        has_hit=any(c['is_hit'] for c in best_cands)
        all_bets.append({'year':test_yr,'type':best_bt,'n':nn,'invest':inv,'payout':payout,'hit':has_hit})

# === 結果 ===
print(f"\n{'='*80}")
print(f"v22g: オッズ補正済み全券種自動選択（1R={BUDGET}円）")
print(f"{'='*80}")
total_inv=sum(r['invest'] for r in all_bets)
total_pay=sum(r['payout'] for r in all_bets)
hit_r=sum(1 for r in all_bets if r['hit'])
print(f"\n全体: {len(all_bets)}R inv={total_inv:,} pay={total_pay:,.0f} rec={total_pay/total_inv*100:.1f}% hit={hit_r}R ({hit_r/len(all_bets):.1%})")
for yr in [2024,2025,2026]:
    sub=[r for r in all_bets if r['year']==yr]
    if not sub: continue
    inv=sum(r['invest'] for r in sub); pay=sum(r['payout'] for r in sub)
    hits=sum(1 for r in sub if r['hit'])
    print(f"  {yr}: {len(sub)}R rec={pay/inv*100:.1f}% PnL={pay-inv:+,.0f} hit={hits}R")

print(f"\n--- 券種別 ---")
by_type=defaultdict(lambda:{'n':0,'invest':0,'payout':0,'hits':0})
for r in all_bets:
    t=by_type[r['type']]; t['n']+=1; t['invest']+=r['invest']; t['payout']+=r['payout']
    if r['hit']: t['hits']+=1
for bt in ['win','umaren','trio','trifecta']:
    d=by_type.get(bt,{'n':0,'invest':0,'payout':0,'hits':0})
    if d['n']==0: continue
    rec=d['payout']/d['invest']*100 if d['invest']>0 else 0
    print(f"  {BT_JP.get(bt,bt):>4}: {d['n']:>5}R inv={d['invest']:>10,} pay={d['payout']:>10,.0f} rec={rec:>6.1f}% hit={d['hits']}R ({d['hits']/d['n']:.1%})")

# v22f（補正なし）との比較
print(f"\n--- v22f（補正なし）との比較 ---")
print(f"  v22f: 8322R rec=135.5% PnL=+6,562,350")
print(f"  v22g: {len(all_bets)}R rec={total_pay/total_inv*100:.1f}% PnL={total_pay-total_inv:+,.0f}")

r_per_year=len(all_bets)/3; annual_pnl=(total_pay-total_inv)/3
print(f"\n年間: {r_per_year:.0f}R/年 PnL={annual_pnl:+,.0f}円/年")

print("\nDone!")
