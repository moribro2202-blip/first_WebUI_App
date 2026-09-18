# -*- coding: utf-8 -*-
"""時系列オッズファイルをパースし、発走N分前のオッズをSQLiteに格納
O1レコード構造:
  pos 0-1:   "O1" レコード種別
  pos 2:     データ区分 (1=通常, 3=確定直前, 4=確定)
  pos 3-10:  作成日 YYYYMMDD
  pos 11-26: 16桁レースキー
  pos 27-30: スナップショット日 MMDD
  pos 31-34: スナップショット時刻 HHMM
  pos 35-36: 登録頭数
  pos 37-42: その他ヘッダ
  pos 43+:   馬ごと8バイト × 頭数: 馬番(2) + 単勝オッズ(4,÷10) + 人気(2)

使い方: python scripts/jravan/parse_ts_odds.py
"""
import os, sys, glob, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
TS_DIR = os.path.join(BASE, 'data', 'jravan_ts')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')

# 発走N分前の候補
MINUTES_BEFORE = [1, 2, 3, 5, 10, 15, 30]

def parse_o1_record(line):
    """O1レコード1行をパース"""
    if len(line) < 43: return None
    s = line if isinstance(line, str) else line.decode('ascii', errors='replace')
    if not s.startswith('O1'): return None

    flag = s[2]
    race_key = s[11:27]
    snap_mmdd = s[27:31]
    snap_hhmm = s[31:35]

    try:
        nhead = int(s[35:37])
    except:
        nhead = 0
    if nhead <= 0 or nhead > 18: return None

    # Parse per-horse odds
    horses = {}
    for i in range(nhead):
        pos = 43 + i * 8
        if pos + 8 > len(s): break
        try:
            hno = int(s[pos:pos+2])
            odds_raw = int(s[pos+2:pos+6])
            odds = odds_raw / 10.0
            pop = int(s[pos+6:pos+8])
            if hno > 0 and odds >= 0:
                horses[hno] = {'odds': odds, 'pop': pop}
        except:
            pass

    return {
        'flag': flag,
        'race_key': race_key,
        'snap_date': snap_mmdd,
        'snap_time': snap_hhmm,
        'nhead': nhead,
        'horses': horses,
    }

def jravan_key_to_jrdb(race_key):
    """16桁JRA-VANキー → JRDB race_id"""
    # YYYYMMDDVVKKHHRR → YYVV{K}{H_hex}RR
    yy = race_key[2:4]
    vv = race_key[8:10]
    kai = int(race_key[10:12])
    day = int(race_key[12:14])
    rr = race_key[14:16]
    day_hex = format(day, 'x')  # 10→a, 11→b, 12→c
    return f'{yy}{vv}{kai}{day_hex}{rr}'

def find_snapshot_at_minutes_before(snapshots, start_time_str, minutes_before):
    """発走N分前に最も近いスナップショットを返す
    start_time_str: "HH:MM" (from races table)
    """
    if not snapshots or not start_time_str:
        return None

    try:
        st_h, st_m = int(start_time_str.split(':')[0]), int(start_time_str.split(':')[1])
    except:
        return None

    # Target time = start_time - N minutes
    target_min = st_h * 60 + st_m - minutes_before

    # Find closest snapshot
    best = None
    best_diff = 999999
    for snap in snapshots:
        try:
            sh = int(snap['snap_time'][:2])
            sm = int(snap['snap_time'][2:4])
            snap_min = sh * 60 + sm
            # Handle day boundary
            sd = snap['snap_date']
            # Simple: just use time difference
            diff = abs(snap_min - target_min)
            if diff < best_diff:
                best_diff = diff
                best = snap
        except:
            pass

    return best

def main():
    print("=== 時系列オッズ パース＆DB格納 ===")

    # Load start times from JRDB
    db = sqlite3.connect(DB_PATH)
    start_times = {}
    for rid, st in db.execute('SELECT race_id, start_time FROM races WHERE start_time IS NOT NULL').fetchall():
        start_times[rid] = st

    # Create table for time-based odds
    db.execute('''CREATE TABLE IF NOT EXISTS ts_win_odds (
        race_id TEXT,
        horse_number INTEGER,
        minutes_before INTEGER,
        odds REAL,
        popularity INTEGER,
        snap_time TEXT,
        PRIMARY KEY (race_id, horse_number, minutes_before)
    )''')
    db.execute('DELETE FROM ts_win_odds')  # Clean rebuild
    db.commit()

    # Process all ts files
    ts_files = sorted(glob.glob(os.path.join(TS_DIR, 'ts_*.txt')))
    print(f"Files to process: {len(ts_files)}")

    total_inserts = 0
    for fi, fpath in enumerate(ts_files):
        fname = os.path.basename(fpath)
        race_key = fname[3:-4]  # "ts_XXXXXXXXXXXXXXXX.txt" → key

        jrdb_rid = jravan_key_to_jrdb(race_key)
        start_time = start_times.get(jrdb_rid)

        # Read all snapshots
        snapshots = []
        with open(fpath, 'rb') as f:
            for line in f:
                rec = parse_o1_record(line)
                if rec:
                    snapshots.append(rec)

        if not snapshots:
            continue

        # For each target minute, find closest snapshot
        for mins in MINUTES_BEFORE:
            snap = find_snapshot_at_minutes_before(snapshots, start_time, mins)
            if not snap:
                continue
            for hno, hdata in snap['horses'].items():
                db.execute(
                    'INSERT OR REPLACE INTO ts_win_odds (race_id, horse_number, minutes_before, odds, popularity, snap_time) VALUES (?,?,?,?,?,?)',
                    (jrdb_rid, hno, mins, hdata['odds'], hdata['pop'], snap['snap_time'])
                )
                total_inserts += 1

        # Also store confirmed (flag=4 or last snapshot)
        confirmed = [s for s in snapshots if s['flag'] == '4']
        final = confirmed[-1] if confirmed else snapshots[-1]
        for hno, hdata in final['horses'].items():
            db.execute(
                'INSERT OR REPLACE INTO ts_win_odds (race_id, horse_number, minutes_before, odds, popularity, snap_time) VALUES (?,?,?,?,?,?)',
                (jrdb_rid, hno, 0, hdata['odds'], hdata['pop'], final['snap_time'])
            )
            total_inserts += 1

        if (fi + 1) % 500 == 0:
            db.commit()
            print(f"  {fi+1}/{len(ts_files)} files, {total_inserts:,} records", flush=True)

    db.commit()
    db.close()

    print(f"\n=== 完了 ===")
    print(f"ファイル: {len(ts_files)}")
    print(f"レコード: {total_inserts:,}")
    print(f"テーブル: ts_win_odds (race_id, horse_number, minutes_before, odds, popularity, snap_time)")
    print(f"minutes_before: 0=確定, {MINUTES_BEFORE}")

if __name__ == '__main__':
    main()
