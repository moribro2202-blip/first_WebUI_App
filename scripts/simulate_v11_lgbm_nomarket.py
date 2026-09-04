"""
v11: LightGBM（市場情報を除外）
- オッズ・市場確率・市場順位を特徴量から除外
- 「市場が見落としている情報」だけを学習
- 予測値をv7と同じ方法でオッズとブレンド（alpha最適化）
"""
import sqlite3, math, sys, numpy as np
from collections import defaultdict
import lightgbm as lgb

out = open(r'C:\Users\moribro2201\Desktop\simulation_v11.txt', 'w', encoding='utf-8')
def p(s=''): out.write(s+'\n')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

p('=== v11: LightGBM（市場情報除外 + ブレンド） ===\n')

BETA=1.03; BUDGET=10000

def mktp(odds):
    inv=[1/o if o>0 else 0 for o in odds]; s=sum(inv)
    if s==0: return [1/len(odds)]*len(odds)
    raw=[i/s for i in inv]; pw=[p_**BETA for p_ in raw]; ps=sum(pw)
    return [p_/ps for p_ in pw]

def blendf(m,mk,alpha):
    bl=[math.exp(alpha*math.log(max(a,1e-10))+(1-alpha)*math.log(max(b,1e-10))) for a,b in zip(m,mk)]
    s=sum(bl); return [p_/s for p_ in bl] if s>0 else bl

races=db.execute('SELECT race_id,race_date,venue_code,surface,distance,race_number FROM races ORDER BY race_date,race_id').fetchall()
entry_cache={}
for rid,_,_,_,_,_ in races:
    es=db.execute('SELECT horse_number,horse_id,jockey_name,carried_weight FROM entries WHERE race_id=?',(rid,)).fetchall()
    if es: entry_cache[rid]={e[0]:{'hid':e[1],'jockey':e[2],'weight':e[3]} for e in es}

jc=defaultdict(lambda:{'r':0,'w':0,'p3':0})
hr=defaultdict(list)
horse_last_race={}

# 市場情報を除外した特徴量
FEATURE_NAMES = [
    'n_horses','horse_number','race_number','carried_weight',
    'jockey_win_rate','jockey_place_rate','jockey_rides',
    'horse_avg_pos','horse_best_pos','horse_runs',
    'horse_win_rate','horse_place_rate',
    'dist_avg','dist_place_rate','surf_avg','venue_avg',
    'trend','days_since',
    'is_turf','distance_cat',
]

def build_features(h, rid, vc, sf, dt, rnum, n_horses):
    ent=entry_cache.get(rid,{}).get(h,{})
    hid=ent.get('hid',''); jn=ent.get('jockey','')
    wt=ent.get('weight',0) or 0
    f={}
    f['n_horses']=n_horses; f['horse_number']=h; f['race_number']=rnum
    f['carried_weight']=wt
    f['is_turf']=1 if sf=='芝' else 0
    f['distance_cat']=0 if dt<=1200 else (1 if dt<=1600 else (2 if dt<=2000 else 3))

    if jn and jn in jc and jc[jn]['r']>=10:
        f['jockey_win_rate']=jc[jn]['w']/jc[jn]['r']
        f['jockey_place_rate']=jc[jn]['p3']/jc[jn]['r']
        f['jockey_rides']=min(jc[jn]['r'],1000)
    else:
        f['jockey_win_rate']=0.08; f['jockey_place_rate']=0.25; f['jockey_rides']=0

    if hid and hid in hr:
        rc=hr[hid]; recent=rc[-5:]
        f['horse_avg_pos']=sum(r['fp'] for r in recent)/len(recent)
        f['horse_best_pos']=min(r['fp'] for r in recent)
        f['horse_runs']=min(len(rc),20)
        f['horse_win_rate']=sum(1 for r in rc if r['fp']==1)/len(rc)
        f['horse_place_rate']=sum(1 for r in rc if r['fp']<=3)/len(rc)
        dr=[r for r in rc if r['dist'] and abs(r['dist']-dt)<=200]
        f['dist_avg']=sum(r['fp'] for r in dr[-5:])/len(dr[-5:]) if len(dr)>=2 else f['horse_avg_pos']
        f['dist_place_rate']=sum(1 for r in dr if r['fp']<=3)/len(dr) if len(dr)>=2 else f['horse_place_rate']
        sr=[r for r in rc if r['surface']==sf]
        f['surf_avg']=sum(r['fp'] for r in sr[-5:])/len(sr[-5:]) if len(sr)>=2 else f['horse_avg_pos']
        vr=[r for r in rc if r['venue']==vc]
        f['venue_avg']=sum(r['fp'] for r in vr[-5:])/len(vr[-5:]) if len(vr)>=2 else f['horse_avg_pos']
        f['trend']=recent[0]['fp']-recent[-1]['fp'] if len(recent)>=3 else 0
        if hid in horse_last_race:
            from datetime import datetime
            try:
                rd_row=db.execute("SELECT race_date FROM races WHERE race_id=?",(rid,)).fetchone()
                if rd_row:
                    f['days_since']=min((datetime.strptime(rd_row[0],'%Y-%m-%d')-datetime.strptime(horse_last_race[hid],'%Y-%m-%d')).days,365)
                else: f['days_since']=30
            except: f['days_since']=30
        else: f['days_since']=180
    else:
        f['horse_avg_pos']=8; f['horse_best_pos']=5; f['horse_runs']=0
        f['horse_win_rate']=0; f['horse_place_rate']=0
        f['dist_avg']=8; f['dist_place_rate']=0; f['surf_avg']=8; f['venue_avg']=8
        f['trend']=0; f['days_since']=180
    return f

# 学習データ構築
X_train=[]; y_train=[]
for rid,rd,vc,sf,dt,rnum in races:
    if rd>='2026-01-01': break
    res=db.execute('SELECT horse_number,finish_position,horse_id FROM results WHERE race_id=? AND finish_position IS NOT NULL',(rid,)).fetchall()
    if len(res)<5: continue
    oz=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
    if not oz: continue
    om={int(r[0]):r[1] for r in oz}; hl=sorted(om.keys())
    if len(hl)<5: continue

    for hn,fp,hid in res:
        if hn not in om: continue
        f=build_features(hn,rid,vc,sf,dt,rnum,len(hl))
        X_train.append([f[k] for k in FEATURE_NAMES])
        y_train.append(1 if fp<=3 else 0)

    for hn,fp,hid in res:
        ent=entry_cache.get(rid,{}).get(hn,{})
        jn=ent.get('jockey','')
        if jn: jc[jn]['r']+=1; fp==1 and jc[jn].__setitem__('w',jc[jn]['w']+1); fp<=3 and jc[jn].__setitem__('p3',jc[jn]['p3']+1)
        if hid:
            hr[hid].append({'fp':fp,'dist':dt,'surface':sf,'venue':vc})
            if len(hr[hid])>20: hr[hid]=hr[hid][-20:]
            horse_last_race[hid]=rd

X_train=np.array(X_train,dtype=np.float32); y_train=np.array(y_train,dtype=np.int32)
p(f'Training: {len(X_train)} samples, positive: {y_train.mean():.3f}')

# LightGBM学習
train_data=lgb.Dataset(X_train,label=y_train,feature_name=FEATURE_NAMES)
params={
    'objective':'binary','metric':'binary_logloss','learning_rate':0.03,
    'num_leaves':24,'max_depth':5,'min_child_samples':80,
    'subsample':0.7,'colsample_bytree':0.7,
    'reg_alpha':0.5,'reg_lambda':2.0,'verbose':-1,'seed':42,
}
model=lgb.train(params,train_data,num_boost_round=200)

p('\n特徴量重要度:')
for fn,imp in sorted(zip(FEATURE_NAMES,model.feature_importance(importance_type='gain')),key=lambda x:-x[1]):
    p(f'  {fn:<25} {imp:>8.1f}')

# 2026年テスト（alpha最適化も同時実施）
p('\nPhase 3: 2026年テスト...')

alpha_results=[]

for alpha_x100 in [5,8,10,12,15,18,20,25,30]:
    alpha=alpha_x100/100.0
    tb=0;tr=0;traces=0;thits=0
    mo=defaultdict(lambda:{'b':0,'r':0,'n':0})

    for rid,rd,vc,sf,dt,rnum in races:
        if rd<'2026-01-01': continue
        res=db.execute('SELECT horse_number,finish_position FROM results WHERE race_id=? AND finish_position IS NOT NULL ORDER BY finish_position',(rid,)).fetchall()
        if len(res)<5: continue
        t3=[r[0] for r in res if r[1]<=3]
        if len(t3)<3: continue
        oz=db.execute("SELECT combination,odds FROM odds WHERE race_id=? AND bet_type='win'",(rid,)).fetchall()
        if not oz: continue
        om={int(r[0]):r[1] for r in oz}; hl=sorted(om.keys())
        if len(hl)<5: continue
        early=[om[h] for h in hl]

        # LightGBM予測
        X_test=[]
        for h in hl:
            f=build_features(h,rid,vc,sf,dt,rnum,len(hl))
            X_test.append([f[k] for k in FEATURE_NAMES])
        preds=model.predict(np.array(X_test,dtype=np.float32))

        # 予測値を正規化して勝率に変換
        psum=sum(preds)
        model_probs=[p_/psum for p_ in preds] if psum>0 else [1/len(hl)]*len(hl)

        # 市場確率とブレンド
        market_probs=mktp(early)
        blended=blendf(model_probs,market_probs,alpha)

        # 上位3頭
        rk=sorted(range(len(hl)),key=lambda i:-blended[i])
        top=[hl[r] for r in rk[:3]]

        combo='-'.join(str(h) for h in sorted(top))
        orow=db.execute("SELECT odds FROM odds WHERE race_id=? AND bet_type='sanrenpuku' AND combination=?",(rid,combo)).fetchone()
        if not orow or orow[0]<=0: continue
        odds=orow[0]; hit=set(top)==set(t3[:3])
        tb+=BUDGET;traces+=1
        month=rd[:7]; mo[month]['b']+=BUDGET; mo[month]['n']+=1
        if hit: tr+=BUDGET*odds; thits+=1; mo[month]['r']+=BUDGET*odds

    rr=tr/tb*100 if tb>0 else 0
    alpha_results.append({'alpha':alpha,'rr':rr,'hits':thits,'races':traces,'profit':tr-tb,'mo':dict(mo)})
    p(f'  alpha={alpha:.2f}: 回収率{rr:>6.1f}% 的中{thits:>4}/{traces} 収支{tr-tb:>+12,.0f}円')

best=max(alpha_results,key=lambda x:x['rr'])
p(f'\nベスト: alpha={best["alpha"]:.2f} 回収率{best["rr"]:.1f}%')

p(f'\n--- 月別: alpha={best["alpha"]:.2f} ---')
cb=0;cr=0
for m in sorted(best['mo'].keys()):
    d=best['mo'][m]; cb+=d['b'];cr+=d['r']
    p(f'  {m}: {d["n"]:>4}R 月{d["r"]/d["b"]*100 if d["b"]>0 else 0:>6.1f}% 累積{cr/cb*100:>6.1f}% 損益{cr-cb:>+10,.0f}円')

p(f'\n=== 比較 ===')
p(f'v7 (手動スコア alpha=0.15):  回収率110.4% 収支+2,044,000円')
p(f'v10(LightGBM 市場含む):     回収率 93.2% 収支-1,342,000円')
p(f'v11(LightGBM 市場除外 alpha={best["alpha"]:.2f}): 回収率{best["rr"]:.1f}% 収支{best["profit"]:+,.0f}円')

db.close(); out.close()
