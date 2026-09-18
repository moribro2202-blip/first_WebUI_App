# -*- coding: utf-8 -*-
"""JRA-VAN 時系列オッズ バックフィル取得（32bit Python専用）
- JRDBのレースIDから16桁JRA-VANキーを生成
- JVRTOpen(0B41)で時系列単複オッズを取得
- レジューム対応（完了レースをJSONに記録）
- 500レースごとにCOMを再生成（メモリリーク回避）

使い方: py -3.12-32 scripts/jravan/backfill_ts_odds.py
"""
import json, os, sys, time, glob

# === 設定 ===
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'jrdb.db')
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'jravan_ts')
DONE_FILE = os.path.join(SAVE_DIR, 'ts_done.json')
BATCH_SIZE = 500  # COMを再生成する間隔
START_YEAR = 2004  # 過去20年分
END_YEAR = 2026

sys.stdout.reconfigure(encoding='utf-8')
os.makedirs(SAVE_DIR, exist_ok=True)

# === JRDB race_id → JRA-VAN 16桁キー ===
def jrdb_to_key(race_id, race_date):
    vv = race_id[2:4]
    kk_raw = race_id[4:6]
    rr = race_id[6:8]
    kai = int(kk_raw[0])
    day = int(kk_raw[1], 16)
    yyyymmdd = race_date.replace('-', '')
    return f'{yyyymmdd}{vv}{kai:02d}{day:02d}{int(rr):02d}'

# === レースキー生成 ===
def load_race_keys():
    import sqlite3
    keys = []

    # 1. JRDB races (2015+)
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        'SELECT race_id, race_date FROM races WHERE race_date >= ? AND race_date < ? ORDER BY race_date, race_id',
        (f'{max(START_YEAR, 2015)}-01-01', f'{END_YEAR+1}-01-01')
    ).fetchall()
    db.close()
    seen = set()
    for rid, rd in rows:
        try:
            key = jrdb_to_key(rid, rd)
            if key not in seen:
                keys.append((rid, key, rd))
                seen.add(key)
        except:
            pass

    # 2. JRA-VAN race_keys.json (2004-2014)
    keys_file = os.path.join(SAVE_DIR, 'race_keys.json')
    if os.path.exists(keys_file):
        import json
        jv_keys = json.load(open(keys_file, encoding='utf-8'))
        for year_str, year_keys in jv_keys.items():
            year = int(year_str)
            if year < START_YEAR or year > END_YEAR: continue
            if year >= 2015: continue  # already covered by JRDB
            for key in year_keys:
                if key not in seen:
                    rd = f'{key[:4]}-{key[4:6]}-{key[6:8]}'
                    keys.append(('jv_' + key, key, rd))
                    seen.add(key)

    return keys

# === レジューム管理 ===
def load_done():
    if os.path.exists(DONE_FILE):
        try:
            return set(json.load(open(DONE_FILE, encoding='utf-8')))
        except:
            pass
    return set()

def save_done(done_set):
    json.dump(sorted(done_set), open(DONE_FILE, 'w', encoding='utf-8'), indent=2)

# === JV-Link操作 ===
def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0:
        raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def fetch_ts_odds(jv, race_key, save_path):
    """1レースの時系列オッズを取得してファイルに保存"""
    ret = jv.JVRTOpen('0B41', race_key)
    if isinstance(ret, tuple):
        code = ret[0]
    else:
        code = ret

    if code < 0:
        return 0  # データなし

    # ダウンロード待ち
    if isinstance(ret, tuple) and len(ret) > 2 and ret[2] > 0:
        needed = ret[2]
        t0 = time.time()
        while jv.JVStatus() < needed:
            if time.time() - t0 > 30:
                break
            time.sleep(0.3)

    # データ読み出し
    records = []
    for _ in range(5000):  # 安全上限
        try:
            r = jv.JVRead(bytearray(200000), 200000, '')
            if isinstance(r, tuple) and len(r) >= 2:
                rc = r[0]
                if rc == 0:
                    break
                if rc == -1:
                    continue
                if rc > 0:
                    data = r[1]
                    if data:
                        if isinstance(data, str):
                            records.append(data.encode('cp932', errors='replace'))
                        else:
                            records.append(bytes(data) if not isinstance(data, bytes) else data)
            else:
                break
        except Exception as e:
            print(f'    Read error: {e}')
            break

    try:
        jv.JVClose()
    except:
        pass

    if records:
        with open(save_path, 'wb') as f:
            for rec in records:
                f.write(rec.rstrip(b'\r\n') + b'\n')

    return len(records)

# === メイン ===
def main():
    print(f'=== JRA-VAN 時系列オッズ バックフィル ===')
    print(f'期間: {START_YEAR}-{END_YEAR}')
    print(f'保存先: {SAVE_DIR}')

    # レースキー読み込み
    all_keys = load_race_keys()
    print(f'対象レース: {len(all_keys)}')

    done = load_done()
    print(f'取得済み: {len(done)}')

    # 未取得のみ
    todo = [(rid, key, rd) for rid, key, rd in all_keys if key not in done]
    print(f'未取得: {len(todo)}')
    if not todo:
        print('全て取得済みです')
        return

    # 直近年から（recent first）
    todo.sort(key=lambda x: x[2], reverse=True)

    jv = create_jv()
    total_records = 0
    batch_count = 0
    start_time = time.time()

    for i, (rid, key, rd) in enumerate(todo):
        save_path = os.path.join(SAVE_DIR, f'ts_{key}.txt')

        try:
            n = fetch_ts_odds(jv, key, save_path)
            total_records += n
            done.add(key)
            batch_count += 1

            # 進捗表示
            if (i + 1) % 10 == 0 or n > 0:
                elapsed = time.time() - start_time
                speed = (i + 1) / elapsed if elapsed > 0 else 0
                remaining = (len(todo) - i - 1) / speed / 60 if speed > 0 else 0
                print(f'  [{i+1}/{len(todo)}] {rd} {rid} → {n}件 ({speed:.1f}R/s, 残{remaining:.0f}分)')

            # 定期保存
            if (i + 1) % 50 == 0:
                save_done(done)

            # COM再生成（メモリリーク回避）
            if batch_count >= BATCH_SIZE:
                try:
                    jv.JVClose()
                except:
                    pass
                del jv
                time.sleep(1)
                jv = create_jv()
                batch_count = 0
                print(f'  [COM再生成 @ {i+1}レース]')

        except Exception as e:
            print(f'  ERROR: {rid} {key}: {e}')
            # COM再生成して続行
            try:
                del jv
            except:
                pass
            time.sleep(2)
            jv = create_jv()
            batch_count = 0
            continue

    # 最終保存
    save_done(done)

    elapsed = time.time() - start_time
    print(f'\n=== 完了 ===')
    print(f'取得: {len(todo)}レース, {total_records}レコード')
    print(f'所要: {elapsed/60:.1f}分')
    print(f'保存: {SAVE_DIR}')

    try:
        jv.JVClose()
    except:
        pass

if __name__ == '__main__':
    main()
