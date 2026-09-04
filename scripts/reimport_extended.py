"""
Pythonで拡張フィールドを直接SQLiteに書き込む
BAC: track_condition, weather, grade, race_class, race_name, head_count
SED: horse_weight, corner_positions
"""
import sqlite3, os, glob, sys
sys.stdout.reconfigure(encoding='utf-8')

db = sqlite3.connect(r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb.db')

def read_lines(filepath):
    with open(filepath, 'rb') as f:
        return f.readlines()

def extract(line, pos, length):
    try:
        raw = line[pos:pos+length]
        return raw.decode('shift_jis', errors='replace').strip()
    except:
        return ''

def extract_ascii(line, pos, length):
    try:
        return line[pos:pos+length].decode('ascii', errors='replace').strip()
    except:
        return ''

TRACK_COND = {"11":"良","12":"稍重","13":"重","14":"不良","21":"良","22":"稍重","23":"重","24":"不良"}
WEATHER = {"1":"晴","2":"曇","3":"雨","4":"小雨","5":"小雪","6":"雪"}

# === BAC: Update races with extended fields ===
print("=== BAC: Updating track_condition, weather, grade, race_class, race_name, head_count ===")
bac_dir = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb\BAC'
bac_files = sorted(glob.glob(os.path.join(bac_dir, '*.txt')))

stmt = db.execute("SELECT COUNT(*) FROM races WHERE track_condition IS NOT NULL").fetchone()[0]
print(f"  Before: {stmt} races with track_condition")

updated = 0
for fpath in bac_files:
    lines = read_lines(fpath)
    for line in lines:
        if len(line) < 87: continue
        venue = extract_ascii(line, 0, 2)
        year = extract_ascii(line, 2, 2)
        kai = extract_ascii(line, 4, 2)
        race_num = extract_ascii(line, 6, 2)
        if not venue or not year or not race_num: continue
        try:
            rn = int(race_num)
        except: continue
        race_id = f"{year}{venue}{kai}{race_num}"

        tc_code = extract_ascii(line, 26, 2)
        track_cond = TRACK_COND.get(tc_code)
        w_code = extract_ascii(line, 28, 1)
        weather = WEATHER.get(w_code)
        syubetsu = extract_ascii(line, 29, 2)
        jouken = extract_ascii(line, 31, 2)
        kigou = extract_ascii(line, 33, 2)
        race_name = extract(line, 35, 50) if len(line) >= 85 else None
        head_str = extract_ascii(line, 85, 2)
        try:
            head_count = int(head_str)
        except:
            head_count = None

        # Grade detection
        grade = None
        if syubetsu == "OP": grade = "OP"
        if kigou == "11": grade = "G1"
        elif kigou == "12": grade = "G2"
        elif kigou == "13": grade = "G3"

        race_class = f"{syubetsu}/{jouken}" if syubetsu and jouken else None

        db.execute("""
            UPDATE races SET
                track_condition = ?,
                weather = ?,
                grade = ?,
                race_class = ?,
                race_name = ?,
                head_count = COALESCE(?, head_count)
            WHERE race_id = ?
        """, (track_cond, weather, grade, race_class, race_name, head_count, race_id))
        updated += 1

db.commit()
print(f"  Updated: {updated} races")
stmt = db.execute("SELECT COUNT(*) FROM races WHERE track_condition IS NOT NULL").fetchone()[0]
print(f"  After: {stmt} races with track_condition")

# Verify
print("\n  Sample:")
for r in db.execute("SELECT race_id, track_condition, weather, grade, race_class, race_name, head_count FROM races WHERE track_condition IS NOT NULL ORDER BY race_date DESC LIMIT 5").fetchall():
    print(f"    {r}")

# === SED: Update results with horse_weight and corner_positions ===
print("\n=== SED: Updating horse_weight, corner_positions ===")
sed_dir = r'C:\Users\moribro2201\Desktop\Cursor\Projects\My_App\first_WebUI_App\data\jrdb\SED'
sed_files = sorted([f for f in glob.glob(os.path.join(sed_dir, '*.txt')) if os.path.basename(f).startswith('SED')])

stmt = db.execute("SELECT COUNT(*) FROM results WHERE horse_weight IS NOT NULL").fetchone()[0]
print(f"  Before: {stmt} results with horse_weight")

updated = 0
for fpath in sed_files:
    lines = read_lines(fpath)
    for line in lines:
        if len(line) < 335: continue
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

        # Horse weight (pos 332-334)
        hw_str = extract_ascii(line, 332, 3)
        horse_weight = None
        try:
            hw = int(hw_str)
            if 350 <= hw <= 600: horse_weight = hw
        except: pass

        # Corner positions (pos 307-320)
        cp_raw = extract_ascii(line, 307, 14)
        corner_positions = None
        if cp_raw:
            corners = []
            for i in range(0, len(cp_raw), 2):
                c = cp_raw[i:i+2].strip()
                if c and c != "00":
                    try:
                        int(c)
                        corners.append(c)
                    except: pass
            if corners:
                corner_positions = "-".join(corners)

        if horse_weight is not None or corner_positions is not None:
            db.execute("""
                UPDATE results SET
                    horse_weight = COALESCE(?, horse_weight),
                    corner_positions = COALESCE(?, corner_positions)
                WHERE race_id = ? AND horse_number = ?
            """, (horse_weight, corner_positions, race_id, hn))
            updated += 1

db.commit()
print(f"  Updated: {updated} results")

# Check coverage
for col in ['horse_weight', 'corner_positions']:
    cnt = db.execute(f"SELECT COUNT(*) FROM results WHERE {col} IS NOT NULL").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    print(f"  {col}: {cnt}/{total} ({cnt/total*100:.1f}%)")

# Verify
print("\n  Sample:")
for r in db.execute("SELECT race_id, horse_number, finish_position, horse_weight, corner_positions FROM results WHERE horse_weight IS NOT NULL ORDER BY race_id DESC LIMIT 5").fetchall():
    print(f"    {r}")

# Summary of all field coverage
print("\n=== Final Data Coverage ===")
for col in ['track_condition', 'weather', 'grade', 'race_class', 'race_name', 'head_count']:
    cnt = db.execute(f"SELECT COUNT(*) FROM races WHERE {col} IS NOT NULL AND {col} != ''").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    print(f"  races.{col}: {cnt}/{total} ({cnt/total*100:.1f}%)")

for col in ['horse_weight', 'corner_positions']:
    cnt = db.execute(f"SELECT COUNT(*) FROM results WHERE {col} IS NOT NULL").fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    print(f"  results.{col}: {cnt}/{total} ({cnt/total*100:.1f}%)")

db.close()
print("\nDone!")
