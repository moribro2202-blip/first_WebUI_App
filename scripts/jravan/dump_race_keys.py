# -*- coding: utf-8 -*-
"""JRA-VAN RACEスペックから16桁レースキーを抽出（32bit Python専用）
2004-2014年のキーをJRA-VANから直接取得する

使い方: py -3.12-32 scripts/jravan/dump_race_keys.py
"""
import json, os, sys, time
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
SAVE_DIR = os.path.join(BASE, 'data', 'jravan_ts')
KEYS_FILE = os.path.join(SAVE_DIR, 'race_keys.json')

START_YEAR = 2004
END_YEAR = 2014  # 2015+ is covered by JRDB

os.makedirs(SAVE_DIR, exist_ok=True)

def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0:
        raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def extract_keys_for_year(jv, year):
    """RACEスペックから1年分のRAレコードのレースキーを抽出"""
    keys = []
    ret = jv.JVOpen('RACE', f'{year}0101000000', 4, 0, 0, '')
    if isinstance(ret, tuple):
        code = ret[0]
        if code < 0 and code != -1:
            print(f'  JVOpen error: {code}')
            return keys
        needed = ret[2] if len(ret) > 2 else 0
        if needed > 0:
            t0 = time.time()
            while jv.JVStatus() < needed:
                if time.time() - t0 > 300:
                    print('  Download timeout')
                    break
                time.sleep(0.5)
    else:
        if ret < 0:
            print(f'  JVOpen error: {ret}')
            return keys

    count = 0
    for _ in range(5000000):  # safety
        try:
            r = jv.JVRead(bytearray(200000), 200000, '')
            if isinstance(r, tuple) and len(r) >= 2:
                rc = r[0]
                if rc == 0: break
                if rc == -1: continue
                if rc > 0:
                    data = r[1]
                    if data and len(data) >= 13:
                        rec_type = data[:2]
                        if rec_type == 'RA':
                            # RA record: type(2) + div(1) + date(8) + race_key(16)
                            # Extract race key from position 11-26
                            if len(data) >= 27:
                                race_key = data[11:27]
                                # Verify it's a valid central race (venue 01-10)
                                venue = race_key[8:10]
                                try:
                                    v = int(venue)
                                    if 1 <= v <= 10:
                                        key_year = int(race_key[:4])
                                        if key_year == year:
                                            keys.append(race_key)
                                except:
                                    pass
                    count += 1
            else:
                break
        except Exception as e:
            print(f'  Read error: {e}')
            break

    try:
        jv.JVClose()
    except:
        pass

    return list(set(keys))  # deduplicate

def main():
    print(f'=== JRA-VAN レースキー抽出 ({START_YEAR}-{END_YEAR}) ===')

    # Load existing keys
    existing = {}
    if os.path.exists(KEYS_FILE):
        try:
            existing = json.load(open(KEYS_FILE, encoding='utf-8'))
        except:
            pass

    jv = create_jv()
    batch = 0

    for year in range(END_YEAR, START_YEAR - 1, -1):  # recent first
        if str(year) in existing:
            print(f'  {year}: already done ({len(existing[str(year)])} keys)')
            continue

        print(f'  {year}: extracting...', flush=True)
        keys = extract_keys_for_year(jv, year)
        print(f'  {year}: {len(keys)} race keys found')

        existing[str(year)] = sorted(keys)
        json.dump(existing, open(KEYS_FILE, 'w', encoding='utf-8'), indent=2)

        batch += 1
        if batch % 3 == 0:
            # Recreate COM
            try: jv.JVClose()
            except: pass
            del jv
            time.sleep(1)
            jv = create_jv()

    try: jv.JVClose()
    except: pass

    total = sum(len(v) for v in existing.values())
    print(f'\n=== 完了: {total:,} keys ({len(existing)} years) ===')

if __name__ == '__main__':
    main()
