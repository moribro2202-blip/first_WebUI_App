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

# --- OT (trio odds) - C(18,3)=816 fixed slots per race ---
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
            slot_idx=0
            for i in range(1,19):
                for j in range(i+1,19):
                    for kk in range(j+1,19):
                        pos=10+slot_idx*6
                        slot_idx += 1
                        if pos+6 > len(line): continue
                        if i > heads or j > heads or kk > heads: continue
                        s=line[pos:pos+6].decode('ascii','replace').strip()
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

# --- HJC (confirmed payouts for all bet types) ---
# HJC format (0-indexed byte positions):
#   Header:      0-7   (8 bytes)
#   Tansho:      8-34  (3 x 9:  uma2+pay7, /100)
#   Fukusho:    35-79  (5 x 9:  uma2+pay7, /100)
#   Wakuren:    80-106 (3 x 9:  combo2+pay7, /100)
#   Umaren:    107-142 (3 x 12: combo4+pay8, /100)
#   Wide:      143-226 (7 x 12: combo4+pay8, /100)
#   Umatan:    227-298 (6 x 12: combo4+pay8, /100)
#   Sanrenpuku: 299-340 (3 x 14: combo6+pay8, /100)
#   Sanrentan:  341-430 (6 x 15: combo6+pay9, /100)
hjc_counts = defaultdict(int)
for fpath in sorted(glob.glob(os.path.join(JRDB, 'HJC', '*.txt'))):
    with open(fpath, 'rb') as f:
        for line in f.readlines():
            if len(line) < 430: continue
            v=line[0:2].decode('ascii','replace').strip()
            y=line[2:4].decode('ascii','replace').strip()
            k=line[4:6].decode('ascii','replace').strip()
            rn=line[6:8].decode('ascii','replace').strip()
            rid=f'{y}{v}{k}{rn}'

            def rd(pos, length):
                return line[pos:pos+length].decode('ascii','replace').strip()

            # Tansho (win): 3 entries x 9 bytes at pos 8
            for i in range(3):
                base = 8 + i*9
                uma = rd(base, 2); pay = rd(base+2, 7)
                try:
                    uma_i = int(uma); pay_i = int(pay)
                    if uma_i <= 0 or pay_i <= 0: continue
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'win_hjc', str(uma_i), pay_i/100))
                    hjc_counts['win'] += 1
                except: pass

            # Fukusho (place): 5 entries x 9 bytes at pos 35
            for i in range(5):
                base = 35 + i*9
                uma = rd(base, 2); pay = rd(base+2, 7)
                try:
                    uma_i = int(uma); pay_i = int(pay)
                    if uma_i <= 0 or pay_i <= 0: continue
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'place_hjc', str(uma_i), pay_i/100))
                    hjc_counts['place'] += 1
                except: pass

            # Umaren: 3 entries x 12 bytes at pos 107
            for i in range(3):
                base = 107 + i*12
                combo_raw = rd(base, 4); pay = rd(base+4, 8)
                try:
                    h1 = int(combo_raw[:2]); h2 = int(combo_raw[2:])
                    pay_i = int(pay)
                    if h1 <= 0 or pay_i <= 0: continue
                    combo = '-'.join(str(x) for x in sorted([h1, h2]))
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'umaren_hjc', combo, pay_i/100))
                    hjc_counts['umaren'] += 1
                except: pass

            # Wide: 7 entries x 12 bytes at pos 143
            for i in range(7):
                base = 143 + i*12
                combo_raw = rd(base, 4); pay = rd(base+4, 8)
                try:
                    h1 = int(combo_raw[:2]); h2 = int(combo_raw[2:])
                    pay_i = int(pay)
                    if h1 <= 0 or pay_i <= 0: continue
                    combo = '-'.join(str(x) for x in sorted([h1, h2]))
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'wide_hjc', combo, pay_i/100))
                    hjc_counts['wide'] += 1
                except: pass

            # Umatan: 6 entries x 12 bytes at pos 227
            for i in range(6):
                base = 227 + i*12
                combo_raw = rd(base, 4); pay = rd(base+4, 8)
                try:
                    h1 = int(combo_raw[:2]); h2 = int(combo_raw[2:])
                    pay_i = int(pay)
                    if h1 <= 0 or pay_i <= 0: continue
                    combo = f'{h1}-{h2}'
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'umatan_hjc', combo, pay_i/100))
                    hjc_counts['umatan'] += 1
                except: pass

            # Sanrenpuku: 3 entries x 14 bytes at pos 299
            for i in range(3):
                base = 299 + i*14
                combo_raw = rd(base, 6); pay = rd(base+6, 8)
                try:
                    h1 = int(combo_raw[:2]); h2 = int(combo_raw[2:4]); h3 = int(combo_raw[4:])
                    pay_i = int(pay)
                    if h1 <= 0 or pay_i <= 0: continue
                    combo = '-'.join(str(x) for x in sorted([h1, h2, h3]))
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'sanrenpuku_hjc', combo, pay_i/100))
                    hjc_counts['sanrenpuku'] += 1
                except: pass

            # Sanrentan: 6 entries x 15 bytes at pos 341
            for i in range(6):
                base = 341 + i*15
                combo_raw = rd(base, 6); pay = rd(base+6, 9)
                try:
                    h1 = int(combo_raw[:2]); h2 = int(combo_raw[2:4]); h3 = int(combo_raw[4:])
                    pay_i = int(pay)
                    if h1 <= 0 or pay_i <= 0: continue
                    combo = f'{h1}-{h2}-{h3}'
                    db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                        (rid, 'sanrentan_hjc', combo, pay_i/100))
                    hjc_counts['sanrentan'] += 1
                except: pass

db.commit()
hjc_total = sum(hjc_counts.values())
print(f"  HJC: {hjc_total} confirmed payouts ({', '.join(f'{k}:{v}' for k,v in sorted(hjc_counts.items()))})", flush=True)

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
