"""
汎用インポートスクリプト
Downloads/data にある全ファイル（ZIP/LZH）を解凍してDBにインポート
使い方: python scripts/import_all.py
"""
import zipfile, os, sqlite3, sys, glob
from collections import defaultdict
sys.stdout.reconfigure(encoding='utf-8')

DL = r'C:\Users\moribro2201\Downloads\data'
JRDB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
DB = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'

PREFIXES = ['BAC','KYI','OZ','OT','OV','OW','OU','SED','SRB','TYB','CHA','UKC','HJC','CYB','KKA','KAB']
VENUE = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}
TRACK = {'11':'良','12':'稍重','13':'重','14':'不良','21':'良','22':'稍重','23':'重','24':'不良'}
WEATHER = {'1':'晴','2':'曇','3':'雨','4':'小雨','5':'小雪','6':'雪'}
RUN_STYLES = {'1':'逃げ','2':'先行','3':'差し','4':'追込','5':'好位差し','6':'自在','7':'後方'}

# === Step 1: Extract ===
print("=== Step 1: Extracting ===", flush=True)
extracted = 0

for zpath in glob.glob(os.path.join(DL, '*.zip')):
    zname = os.path.basename(zpath).upper()
    for prefix in PREFIXES:
        if zname.startswith(prefix):
            target = os.path.join(JRDB, prefix)
            os.makedirs(target, exist_ok=True)
            try:
                with zipfile.ZipFile(zpath) as zf:
                    for m in zf.namelist():
                        if m.endswith('.txt'):
                            with open(os.path.join(target, os.path.basename(m)), 'wb') as f:
                                f.write(zf.read(m))
                            extracted += 1
            except Exception as e:
                print(f"  Error: {zname}: {e}")
            break

try:
    import lhafile
    for lpath in glob.glob(os.path.join(DL, '*.lzh')):
        lname = os.path.basename(lpath).upper()
        for prefix in PREFIXES:
            if lname.startswith(prefix):
                target = os.path.join(JRDB, prefix)
                os.makedirs(target, exist_ok=True)
                try:
                    lzh = lhafile.Lhafile(lpath)
                    for info in lzh.infolist():
                        data = lzh.read(info.filename)
                        with open(os.path.join(target, os.path.basename(info.filename)), 'wb') as f:
                            f.write(data)
                        extracted += 1
                except: pass
                break
except: pass

print(f"  Extracted: {extracted} files", flush=True)

# === Step 2: Import ===
db = sqlite3.connect(DB)
print("\n=== Step 2: Importing ===", flush=True)

# --- BAC ---
bac_count = 0
for fpath in sorted(glob.glob(os.path.join(JRDB, 'BAC', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 26: continue
            v=line[0:2].decode('ascii','replace').strip()
            y=line[2:4].decode('ascii','replace').strip()
            k=line[4:6].decode('ascii','replace').strip()
            rn=line[6:8].decode('ascii','replace').strip()
            if not v or not y: continue
            rid=f'{y}{v}{k}{rn}'
            dr=line[8:16].decode('ascii','replace').strip()
            rd=f'{dr[:4]}-{dr[4:6]}-{dr[6:8]}'
            dist=int(line[20:24].decode('ascii','replace').strip() or '0')
            sf={'1':'芝','2':'ダート','3':'障害'}.get(line[24:25].decode('ascii','replace'),'?')
            di={'1':'右','2':'左','3':'直線'}.get(line[25:26].decode('ascii','replace'),'右')
            tc=TRACK.get(line[26:28].decode('ascii','replace').strip())
            w=WEATHER.get(line[28:29].decode('ascii','replace').strip())
            syubetsu=line[29:31].decode('ascii','replace').strip()
            try:
                nm=line[35:85].decode('shift_jis','ignore').strip().replace('\u3000',' ').strip()
            except: nm=None
            grade=None
            if nm and nm[0].isdigit():
                gc=nm[0]; nm=nm[1:].strip()
                grade={'1':'G1','2':'G2','3':'G3'}.get(gc, 'OP' if syubetsu=='OP' else None)
            elif syubetsu=='OP': grade='OP'
            tr=line[16:20].decode('ascii','replace').strip()
            st=f'{tr[:2]}:{tr[2:]}' if len(tr)==4 else None
            db.execute('INSERT OR REPLACE INTO races (race_id,race_date,venue_code,venue_name,race_number,distance,surface,start_time,course_direction,track_condition,weather,race_name,grade) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid,rd,v,VENUE.get(v,v),int(rn),dist,sf,st,di,tc,w,nm or None,grade))
            bac_count += 1
db.commit()
print(f"  BAC: {bac_count} races", flush=True)

# --- KYI ---
kyi_count = 0
for fpath in sorted(glob.glob(os.path.join(JRDB, 'KYI', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 200: continue
            v=line[0:2].decode('ascii','replace').strip()
            y=line[2:4].decode('ascii','replace').strip()
            k=line[4:6].decode('ascii','replace').strip()
            rn=line[6:8].decode('ascii','replace').strip()
            hn=line[8:10].decode('ascii','replace').strip()
            if not v or not y or not hn: continue
            try: hn_i=int(hn)
            except: continue
            rid=f'{y}{v}{k}{rn}'
            hid=line[10:18].decode('ascii','replace').strip()
            try: hname=line[18:48].decode('shift_jis','ignore').strip()
            except: hname=''
            try: jockey=line[171:183].decode('shift_jis','ignore').strip()
            except: jockey=''
            try: trainer=line[187:199].decode('shift_jis','ignore').strip()
            except: trainer=''
            try: cw=int(line[183:186].decode('ascii','replace').strip())/10
            except: cw=0
            try: idm=float(line[54:59].decode('ascii','replace').strip())
            except: idm=None
            try: rider=float(line[59:64].decode('ascii','replace').strip())
            except: rider=None
            try: total=float(line[74:79].decode('ascii','replace').strip())
            except: total=None
            rs=RUN_STYLES.get(line[85:86].decode('ascii','replace').strip())
            da=line[80:81].decode('ascii','replace').strip()
            db.execute('INSERT OR REPLACE INTO entries (race_id,horse_number,horse_id,horse_name,jockey_name,trainer_name,carried_weight,idm,rider_index,total_index,run_style,distance_aptitude) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid,hn_i,hid,hname,jockey,trainer,cw,idm,rider,total,rs,da))
            kyi_count += 1
db.commit()
print(f"  KYI: {kyi_count} entries", flush=True)

# --- OZ (win odds, no /10) ---
oz_count = 0
for fpath in sorted(glob.glob(os.path.join(JRDB, 'OZ', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 100: continue
            v=line[0:2].decode('ascii','replace').strip()
            y=line[2:4].decode('ascii','replace').strip()
            k=line[4:6].decode('ascii','replace').strip()
            rn=line[6:8].decode('ascii','replace').strip()
            rid=f'{y}{v}{k}{rn}'
            try: heads=int(line[8:10].decode('ascii','replace').strip())
            except: heads=18
            for i in range(min(heads, 18)):
                s=line[10+i*5:15+i*5].decode('ascii','replace').strip()
                try:
                    o=float(s)
                    if o > 0:
                        db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)', (rid,'win',str(i+1),o))
                        oz_count += 1
                except: pass
db.commit()
print(f"  OZ: {oz_count} win odds", flush=True)

# --- OT (trio odds) ---
ot_count = 0
for fpath in sorted(glob.glob(os.path.join(JRDB, 'OT', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 20: continue
            v=line[0:2].decode('ascii','replace').strip()
            y=line[2:4].decode('ascii','replace').strip()
            k=line[4:6].decode('ascii','replace').strip()
            rn=line[6:8].decode('ascii','replace').strip()
            rid=f'{y}{v}{k}{rn}'
            try: heads=int(line[8:10].decode('ascii','replace').strip())
            except: continue
            idx=0
            for i in range(1,heads+1):
                for j in range(i+1,heads+1):
                    for kk in range(j+1,heads+1):
                        pos=10+idx*6
                        if pos+6 > len(line): break
                        s=line[pos:pos+6].decode('ascii','replace').strip()
                        idx += 1
                        try:
                            o=float(s)
                            if o > 0 and o < 9999:
                                db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)', (rid,'sanrenpuku',f'{i}-{j}-{kk}',o))
                                ot_count += 1
                        except: pass
db.commit()
print(f"  OT: {ot_count} trio odds", flush=True)

# --- SED (results) ---
sed_count = 0
for fpath in sorted(glob.glob(os.path.join(JRDB, 'SED', 'SED*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 182: continue
            v=line[0:2].decode('ascii','replace').strip()
            y=line[2:4].decode('ascii','replace').strip()
            k=line[4:6].decode('ascii','replace').strip()
            rn=line[6:8].decode('ascii','replace').strip()
            hn=line[8:10].decode('ascii','replace').strip()
            if not v or not y or not hn: continue
            try: hn_i=int(hn)
            except: continue
            rid=f'{y}{v}{k}{rn}'
            hid=line[10:18].decode('ascii','replace').strip()
            try: fp=int(line[140:142].decode('ascii','replace').strip())
            except: fp=None
            try: ft=int(line[142:147].decode('ascii','replace').strip())/10
            except: ft=None
            try: cw=int(line[147:150].decode('ascii','replace').strip())/10
            except: cw=None
            try: jockey=line[150:158].decode('shift_jis','ignore').strip()
            except: jockey=''
            try: win_odds=float(line[174:180].decode('ascii','replace').strip())
            except: win_odds=None
            try: pop=int(line[180:182].decode('ascii','replace').strip())
            except: pop=None
            hw=None
            if len(line)>=335:
                try:
                    hw_val=int(line[332:335].decode('ascii','replace').strip())
                    if 350<=hw_val<=600: hw=hw_val
                except: pass
            cp=None
            if len(line)>=321:
                cp_raw=line[307:321].decode('ascii','replace').strip()
                if cp_raw:
                    corners=[]
                    for ci in range(0,len(cp_raw),2):
                        c=cp_raw[ci:ci+2].strip()
                        if c and c!='00':
                            try: int(c); corners.append(c)
                            except: pass
                    if corners: cp='-'.join(corners)
            db.execute('INSERT OR REPLACE INTO results (race_id,horse_number,horse_id,finish_position,finish_time,jockey_name,carried_weight,win_odds,popularity,horse_weight,corner_positions) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (rid,hn_i,hid,fp,ft,jockey,cw,win_odds,pop,hw,cp))
            sed_count += 1
db.commit()
print(f"  SED: {sed_count} results", flush=True)

# === Step 3: Summary ===
print("\n=== Summary ===", flush=True)

# Find latest dates with data
for label, query in [
    ("Latest race date", "SELECT MAX(race_date) FROM races"),
    ("Latest with entries", "SELECT MAX(r.race_date) FROM races r JOIN entries e ON r.race_id=e.race_id WHERE e.idm IS NOT NULL"),
    ("Latest with win odds", "SELECT MAX(r.race_date) FROM races r JOIN odds o ON r.race_id=o.race_id WHERE o.bet_type='win'"),
    ("Latest with results", "SELECT MAX(r.race_date) FROM races r JOIN results res ON r.race_id=res.race_id WHERE res.finish_position IS NOT NULL"),
]:
    val = db.execute(query).fetchone()[0]
    print(f"  {label}: {val}")

# Check tomorrow's data
import datetime
tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
today = datetime.date.today().isoformat()
for date in [today, tomorrow]:
    races = db.execute('SELECT COUNT(*) FROM races WHERE race_date=?', (date,)).fetchone()[0]
    ent = db.execute('SELECT COUNT(*) FROM entries WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?)', (date,)).fetchone()[0]
    oz = db.execute('SELECT COUNT(*) FROM odds WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?) AND bet_type="win"', (date,)).fetchone()[0]
    status = "✅ Ready" if races > 0 and ent > 0 and oz > 0 else "❌ Missing data" if races > 0 else "- No races"
    print(f"  {date}: {races}R entries={ent} odds={oz} {status}")

db.close()
print("\nDone!", flush=True)
