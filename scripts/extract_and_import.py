"""
1. Downloads/data のZIPを解凍してjrdbディレクトリに配置
2. TYB: IDM・総合指数・馬体重をDBにインポート
3. KYI: IDM・脚質コードをDBにインポート
"""
import sqlite3, os, glob, zipfile, sys
sys.stdout.reconfigure(encoding='utf-8')

DL_DIR = r'C:\Users\moribro2201\Downloads\data'
JRDB_DIR = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb'
DB_PATH = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db'

# === Step 1: Extract ZIPs ===
print("=== Step 1: Extracting ZIPs ===", flush=True)

zip_files = sorted(glob.glob(os.path.join(DL_DIR, '*.zip')))
print(f"  Found {len(zip_files)} ZIP files", flush=True)

extracted = {'TYB': 0, 'KYI': 0, 'CHA': 0}
for zpath in zip_files:
    zname = os.path.basename(zpath)
    # Determine file type from name (TYB_2019.zip, TYB260104.zip, KYI_2020.zip, etc.)
    for prefix in ['TYB', 'KYI', 'CHA']:
        if zname.startswith(prefix):
            target_dir = os.path.join(JRDB_DIR, prefix)
            os.makedirs(target_dir, exist_ok=True)
            try:
                with zipfile.ZipFile(zpath, 'r') as zf:
                    for member in zf.namelist():
                        if member.endswith('.txt'):
                            # Extract only if not already exists
                            target_path = os.path.join(target_dir, os.path.basename(member))
                            if not os.path.exists(target_path):
                                # Extract to target dir
                                data = zf.read(member)
                                with open(target_path, 'wb') as f:
                                    f.write(data)
                                extracted[prefix] += 1
            except Exception as e:
                print(f"  Error extracting {zname}: {e}", flush=True)
            break

for k, v in extracted.items():
    total = len(glob.glob(os.path.join(JRDB_DIR, k, '*.txt')))
    print(f"  {k}: extracted {v} new files, total {total} files", flush=True)

# === Step 2: Check existing DB schema for new columns ===
print("\n=== Step 2: Adding new columns if needed ===", flush=True)
db = sqlite3.connect(DB_PATH)

# Add columns to entries if not exist
existing_cols = {r[1] for r in db.execute("PRAGMA table_info(entries)").fetchall()}
new_entry_cols = {
    'idm': 'REAL',
    'rider_index': 'REAL',
    'info_index': 'REAL',
    'total_index': 'REAL',
    'run_style': 'TEXT',
    'distance_aptitude': 'TEXT',
}
for col, typ in new_entry_cols.items():
    if col not in existing_cols:
        db.execute(f"ALTER TABLE entries ADD COLUMN {col} {typ}")
        print(f"  Added entries.{col}", flush=True)

# Add columns to results if not exist
existing_cols = {r[1] for r in db.execute("PRAGMA table_info(results)").fetchall()}
new_result_cols = {
    'horse_weight_diff': 'INTEGER',
}
for col, typ in new_result_cols.items():
    if col not in existing_cols:
        db.execute(f"ALTER TABLE results ADD COLUMN {col} {typ}")
        print(f"  Added results.{col}", flush=True)

db.commit()

# === Step 3: Import TYB data ===
print("\n=== Step 3: Importing TYB (IDM, total_index, weight) ===", flush=True)

def extract_ascii(line, pos, length):
    try:
        return line[pos:pos+length].decode('ascii', errors='replace').strip()
    except:
        return ''

tyb_dir = os.path.join(JRDB_DIR, 'TYB')
tyb_files = sorted(glob.glob(os.path.join(tyb_dir, '*.txt')))
print(f"  TYB files: {len(tyb_files)}", flush=True)

# TYB format (128 bytes/line):
# 0-1: venue(2), 2-3: year(2), 4-5: kai(2), 6-7: race(2), 8-9: horse_num(2)
# 10-14: IDM(5, float), 15-19: rider_idx(5), 20-24: info_idx(5)
# 25-29: ?(5), 30-34: ?(5), 35-39: ?(5)
# 40-44: total_idx(5, float)
# 88-90: horse_weight(3), 91: weight_diff_sign(+/-), 92-93: weight_diff(2)

updated = 0
batch_size = 0
for fpath in tyb_files:
    with open(fpath, 'rb') as f:
        lines = f.readlines()
    for line in lines:
        if len(line) < 95: continue
        venue = extract_ascii(line, 0, 2)
        year = extract_ascii(line, 2, 2)
        kai = extract_ascii(line, 4, 2)
        race_num = extract_ascii(line, 6, 2)
        horse_num_str = extract_ascii(line, 8, 2)
        if not venue or not year or not race_num or not horse_num_str: continue
        try:
            hn = int(horse_num_str)
        except: continue
        race_id = f"{year}{venue}{kai}{race_num}"

        # IDM
        idm_str = extract_ascii(line, 10, 5)
        try: idm = float(idm_str)
        except: idm = None

        # Rider index
        rider_str = extract_ascii(line, 15, 5)
        try: rider_idx = float(rider_str)
        except: rider_idx = None

        # Info index
        info_str = extract_ascii(line, 20, 5)
        try: info_idx = float(info_str)
        except: info_idx = None

        # Total index
        total_str = extract_ascii(line, 40, 5)
        try: total_idx = float(total_str)
        except: total_idx = None

        # Horse weight from TYB (pos 88-90)
        hw_str = extract_ascii(line, 88, 3)
        try:
            hw = int(hw_str)
            if hw < 350 or hw > 600: hw = None
        except: hw = None

        # Weight diff (pos 91: sign, pos 92-93: value)
        wd = None
        if hw and len(line) >= 94:
            sign = extract_ascii(line, 91, 1)
            diff_str = extract_ascii(line, 92, 2)
            try:
                diff_val = int(diff_str)
                if sign == '-': diff_val = -diff_val
                wd = diff_val
            except: pass

        # Update entries with IDM etc
        db.execute("""
            UPDATE entries SET
                idm = COALESCE(?, idm),
                rider_index = COALESCE(?, rider_index),
                info_index = COALESCE(?, info_index),
                total_index = COALESCE(?, total_index)
            WHERE race_id = ? AND horse_number = ?
        """, (idm, rider_idx, info_idx, total_idx, race_id, hn))

        # Update results with weight from TYB (more reliable than SED)
        if hw:
            db.execute("""
                UPDATE results SET
                    horse_weight = COALESCE(?, horse_weight),
                    horse_weight_diff = COALESCE(?, horse_weight_diff)
                WHERE race_id = ? AND horse_number = ?
            """, (hw, wd, race_id, hn))

        updated += 1
        batch_size += 1
        if batch_size >= 10000:
            db.commit()
            batch_size = 0

db.commit()
print(f"  TYB: Updated {updated} entries", flush=True)

# === Step 4: Import KYI extended fields ===
print("\n=== Step 4: Importing KYI extended (IDM, run_style) ===", flush=True)

kyi_dir = os.path.join(JRDB_DIR, 'KYI')
kyi_files = sorted(glob.glob(os.path.join(kyi_dir, '*.txt')))
print(f"  KYI files: {len(kyi_files)}", flush=True)

# KYI extended fields:
# pos 54-58: IDM(5, float) - prediction IDM
# pos 59-63: rider(5, float)
# pos 64-68: info(5, float)
# pos 74-78: total(5, float)
# pos 78 or 79: run_style code (1)
#   1=逃げ, 2=先行, 3=差し, 4=追込, 5=好位差し
# pos 80: distance aptitude (1)

RUN_STYLES = {'1': '逃げ', '2': '先行', '3': '差し', '4': '追込', '5': '好位差し'}

updated = 0
batch_size = 0
for fpath in kyi_files:
    with open(fpath, 'rb') as f:
        lines = f.readlines()
    for line in lines:
        if len(line) < 200: continue
        venue = extract_ascii(line, 0, 2)
        year = extract_ascii(line, 2, 2)
        kai = extract_ascii(line, 4, 2)
        race_num = extract_ascii(line, 6, 2)
        horse_num_str = extract_ascii(line, 8, 2)
        if not venue or not year or not race_num or not horse_num_str: continue
        try:
            hn = int(horse_num_str)
        except: continue
        race_id = f"{year}{venue}{kai}{race_num}"

        # IDM from KYI (prediction version)
        idm_str = extract_ascii(line, 54, 5)
        try: idm = float(idm_str)
        except: idm = None

        # Total index from KYI
        total_str = extract_ascii(line, 74, 5)
        try: total_idx = float(total_str)
        except: total_idx = None

        # Run style (pos 78, 1 byte)
        rs_code = extract_ascii(line, 78, 1)
        run_style = RUN_STYLES.get(rs_code)

        # Distance aptitude (pos 80, 1 byte)
        da_code = extract_ascii(line, 80, 1)

        # Only update if TYB hasn't already set better values
        db.execute("""
            UPDATE entries SET
                idm = COALESCE(idm, ?),
                total_index = COALESCE(total_index, ?),
                run_style = COALESCE(?, run_style),
                distance_aptitude = COALESCE(?, distance_aptitude)
            WHERE race_id = ? AND horse_number = ?
        """, (idm, total_idx, run_style, da_code, race_id, hn))

        updated += 1
        batch_size += 1
        if batch_size >= 10000:
            db.commit()
            batch_size = 0

db.commit()
print(f"  KYI: Updated {updated} entries", flush=True)

# === Step 5: Coverage check ===
print("\n=== Final Coverage ===", flush=True)
for col in ['idm', 'rider_index', 'info_index', 'total_index', 'run_style', 'distance_aptitude']:
    cnt = db.execute(f"SELECT COUNT(*) FROM entries WHERE {col} IS NOT NULL").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    print(f"  entries.{col}: {cnt}/{total} ({cnt/total*100:.1f}%)", flush=True)

for col in ['horse_weight', 'horse_weight_diff', 'corner_positions']:
    cnt = db.execute(f"SELECT COUNT(*) FROM results WHERE {col} IS NOT NULL").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    print(f"  results.{col}: {cnt}/{total} ({cnt/total*100:.1f}%)", flush=True)

for col in ['track_condition', 'weather', 'race_class']:
    cnt = db.execute(f"SELECT COUNT(*) FROM races WHERE {col} IS NOT NULL AND {col} != ''").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    print(f"  races.{col}: {cnt}/{total} ({cnt/total*100:.1f}%)", flush=True)

# Sample
print("\n=== Sample entries with IDM ===")
for r in db.execute("SELECT race_id, horse_number, idm, total_index, run_style FROM entries WHERE idm IS NOT NULL ORDER BY race_id DESC LIMIT 5").fetchall():
    print(f"  {r}")

# Check year coverage for TYB
print("\n=== TYB year coverage ===")
for year in range(2019, 2027):
    cnt = db.execute(f"SELECT COUNT(*) FROM entries WHERE idm IS NOT NULL AND race_id LIKE '{year-2000}%'").fetchone()[0]
    print(f"  {year}: {cnt} entries with IDM")

db.close()
print("\nDone!", flush=True)
