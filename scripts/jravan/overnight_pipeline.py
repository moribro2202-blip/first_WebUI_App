# -*- coding: utf-8 -*-
"""夜間自動パイプライン（32bit Python専用）
1. 2015-2023年のTSオッズ取得（JRDBキー使用）
2. 2004-2014年キー抽出の完了待ち → TSオッズ取得
3. 全期間パース → DB格納
4. バックテスト実行

使い方: py -3.12-32 scripts/jravan/overnight_pipeline.py
"""
import json, os, sys, time, glob, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
SAVE_DIR = os.path.join(BASE, 'data', 'jravan_ts')
DONE_FILE = os.path.join(SAVE_DIR, 'ts_done.json')
KEYS_FILE = os.path.join(SAVE_DIR, 'race_keys.json')
BATCH_SIZE = 500

os.makedirs(SAVE_DIR, exist_ok=True)

def jrdb_to_key(race_id, race_date):
    vv = race_id[2:4]
    kk_raw = race_id[4:6]
    rr = race_id[6:8]
    kai = int(kk_raw[0])
    day = int(kk_raw[1], 16)
    yyyymmdd = race_date.replace('-', '')
    return f'{yyyymmdd}{vv}{kai:02d}{day:02d}{int(rr):02d}'

def load_done():
    if os.path.exists(DONE_FILE):
        try: return set(json.load(open(DONE_FILE, encoding='utf-8')))
        except: pass
    return set()

def save_done(done_set):
    json.dump(sorted(done_set), open(DONE_FILE, 'w', encoding='utf-8'))

def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0: raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def fetch_ts_odds(jv, race_key, save_path):
    ret = jv.JVRTOpen('0B41', race_key)
    if isinstance(ret, tuple): code = ret[0]
    else: code = ret
    if code < 0: return 0
    if isinstance(ret, tuple) and len(ret) > 2 and ret[2] > 0:
        t0 = time.time()
        while jv.JVStatus() < ret[2]:
            if time.time() - t0 > 30: break
            time.sleep(0.3)
    records = []
    for _ in range(5000):
        try:
            r = jv.JVRead(bytearray(200000), 200000, '')
            if isinstance(r, tuple) and len(r) >= 2:
                rc = r[0]
                if rc == 0: break
                if rc == -1: continue
                if rc > 0:
                    data = r[1]
                    if data:
                        if isinstance(data, str): records.append(data.encode('cp932', errors='replace'))
                        else: records.append(bytes(data) if not isinstance(data, bytes) else data)
            else: break
        except: break
    try: jv.JVClose()
    except: pass
    if records:
        with open(save_path, 'wb') as f:
            for rec in records:
                f.write(rec.rstrip(b'\r\n') + b'\n')
    return len(records)

def backfill_keys(keys_todo, label):
    """指定キーリストのTSオッズを取得"""
    done = load_done()
    todo = [(key, rd) for key, rd in keys_todo if key not in done]
    if not todo:
        print(f'  {label}: 全て取得済み')
        return

    print(f'  {label}: {len(todo)}レース取得開始')
    jv = create_jv()
    batch_count = 0
    start_time = time.time()

    for i, (key, rd) in enumerate(todo):
        save_path = os.path.join(SAVE_DIR, f'ts_{key}.txt')
        try:
            n = fetch_ts_odds(jv, key, save_path)
            done.add(key)
            batch_count += 1
            if (i+1) % 50 == 0:
                save_done(done)
                elapsed = time.time() - start_time
                speed = (i+1) / elapsed if elapsed > 0 else 0
                remaining = (len(todo)-i-1) / speed / 60 if speed > 0 else 0
                print(f'    [{i+1}/{len(todo)}] {rd} {n}件 ({speed:.1f}R/s, 残{remaining:.0f}分)')
            if batch_count >= BATCH_SIZE:
                try: jv.JVClose()
                except: pass
                del jv; time.sleep(1)
                jv = create_jv(); batch_count = 0
        except Exception as e:
            print(f'    ERROR: {key}: {e}')
            try: del jv
            except: pass
            time.sleep(2)
            jv = create_jv(); batch_count = 0

    save_done(done)
    try: jv.JVClose()
    except: pass
    elapsed = time.time() - start_time
    print(f'  {label}: 完了 ({len(todo)}R, {elapsed/60:.1f}分)')

def main():
    print(f'{"="*60}')
    print(f'=== 夜間自動パイプライン 開始 ===')
    print(f'=== {time.strftime("%Y-%m-%d %H:%M:%S")} ===')
    print(f'{"="*60}')

    # === Phase 1: 2015-2023年TSオッズ取得 ===
    print(f'\n--- Phase 1: 2015-2023年 TSオッズ取得 (JRDBキー) ---')
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        'SELECT race_id, race_date FROM races WHERE race_date >= "2015-01-01" AND race_date < "2024-01-01" ORDER BY race_date DESC, race_id'
    ).fetchall()
    db.close()
    keys_2015_2023 = []
    for rid, rd in rows:
        try:
            key = jrdb_to_key(rid, rd)
            keys_2015_2023.append((key, rd))
        except: pass
    print(f'  JRDBキー: {len(keys_2015_2023)}レース')
    backfill_keys(keys_2015_2023, '2015-2023')

    # === Phase 2: 2004-2014年キー抽出待ち → TSオッズ取得 ===
    print(f'\n--- Phase 2: 2004-2014年 キー抽出完了待ち ---')
    wait_start = time.time()
    while True:
        if os.path.exists(KEYS_FILE):
            try:
                jv_keys = json.load(open(KEYS_FILE, encoding='utf-8'))
                years_done = set(int(y) for y in jv_keys.keys())
                needed = set(range(2004, 2015))
                if needed.issubset(years_done):
                    print(f'  キー抽出完了!')
                    break
                else:
                    missing = needed - years_done
                    print(f'  待機中... 未完了年: {sorted(missing)} ({time.strftime("%H:%M:%S")})')
            except:
                pass
        if time.time() - wait_start > 18000:  # 5時間タイムアウト
            print(f'  タイムアウト（5時間）。2004-2014はスキップ。')
            break
        time.sleep(60)  # 1分ごとにチェック

    # 2004-2014キーがあれば取得
    if os.path.exists(KEYS_FILE):
        try:
            jv_keys = json.load(open(KEYS_FILE, encoding='utf-8'))
            keys_2004_2014 = []
            for year_str, year_keys in jv_keys.items():
                year = int(year_str)
                if 2004 <= year <= 2014:
                    for key in year_keys:
                        rd = f'{key[:4]}-{key[4:6]}-{key[6:8]}'
                        keys_2004_2014.append((key, rd))
            if keys_2004_2014:
                print(f'\n--- Phase 2b: 2004-2014年 TSオッズ取得 ---')
                # Recent first
                keys_2004_2014.sort(key=lambda x: x[1], reverse=True)
                backfill_keys(keys_2004_2014, '2004-2014')
        except Exception as e:
            print(f'  2004-2014キー読込エラー: {e}')

    # === Phase 3: パース ===
    print(f'\n--- Phase 3: 全データパース ---')
    ts_files = glob.glob(os.path.join(SAVE_DIR, 'ts_*.txt'))
    print(f'  ファイル数: {len(ts_files)}')

    # Import parse function
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from parse_ts_odds import parse_o1_record, jravan_key_to_jrdb, find_snapshot_at_minutes_before

    db = sqlite3.connect(DB_PATH)
    start_times = {}
    for rid, st in db.execute('SELECT race_id, start_time FROM races WHERE start_time IS NOT NULL').fetchall():
        start_times[rid] = st

    db.execute('''CREATE TABLE IF NOT EXISTS ts_win_odds (
        race_id TEXT, horse_number INTEGER, minutes_before INTEGER,
        odds REAL, popularity INTEGER, snap_time TEXT,
        PRIMARY KEY (race_id, horse_number, minutes_before))''')
    db.execute('DELETE FROM ts_win_odds')
    db.commit()

    MINUTES_BEFORE = [3, 5, 10, 15, 30]
    total_inserts = 0
    for fi, fpath in enumerate(sorted(ts_files)):
        fname = os.path.basename(fpath)
        race_key = fname[3:-4]
        jrdb_rid = jravan_key_to_jrdb(race_key)
        start_time = start_times.get(jrdb_rid)
        snapshots = []
        with open(fpath, 'rb') as f:
            for line in f:
                rec = parse_o1_record(line)
                if rec: snapshots.append(rec)
        if not snapshots: continue

        for mins in MINUTES_BEFORE:
            snap = find_snapshot_at_minutes_before(snapshots, start_time, mins)
            if not snap: continue
            for hno, hdata in snap['horses'].items():
                db.execute('INSERT OR REPLACE INTO ts_win_odds VALUES (?,?,?,?,?,?)',
                    (jrdb_rid, hno, mins, hdata['odds'], hdata['pop'], snap['snap_time']))
                total_inserts += 1

        confirmed = [s for s in snapshots if s['flag'] == '4']
        final = confirmed[-1] if confirmed else snapshots[-1]
        for hno, hdata in final['horses'].items():
            db.execute('INSERT OR REPLACE INTO ts_win_odds VALUES (?,?,?,?,?,?)',
                (jrdb_rid, hno, 0, hdata['odds'], hdata['pop'], final['snap_time']))
            total_inserts += 1

        if (fi+1) % 1000 == 0:
            db.commit()
            print(f'    {fi+1}/{len(ts_files)} files, {total_inserts:,} records')

    db.commit()
    db.close()
    print(f'  パース完了: {total_inserts:,} records')

    # === Phase 4: サマリー ===
    print(f'\n{"="*60}')
    print(f'=== パイプライン完了 ===')
    print(f'=== {time.strftime("%Y-%m-%d %H:%M:%S")} ===')
    print(f'{"="*60}')

    db = sqlite3.connect(DB_PATH)
    for mb in [0, 3, 5, 10, 15, 30]:
        n = db.execute('SELECT COUNT(DISTINCT race_id) FROM ts_win_odds WHERE minutes_before=?',(mb,)).fetchone()[0]
        print(f'  {mb}分前: {n} races')
    db.close()

    total_files = len(glob.glob(os.path.join(SAVE_DIR, 'ts_*.txt')))
    print(f'  TSファイル総数: {total_files}')
    print(f'\n  次のステップ: python scripts/jravan/backtest_5min.py を実行してください')

if __name__ == '__main__':
    main()
