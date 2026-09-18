# -*- coding: utf-8 -*-
"""JRA-VANから上がり3Fデータを取得してDBに格納（32bit Python専用）
SEレコード（成績）から各馬の上がり3Fタイムを抽出。

使い方: py -3.12-32 scripts/jravan/download_last3f.py
"""
import os, sys, time, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
START_YEAR = 2015
END_YEAR = 2026

def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0: raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def jravan_key_to_jrdb(key16):
    """JRA-VAN 16桁キー → JRDB race_id"""
    yy = key16[2:4]; vv = key16[8:10]
    kai = int(key16[10:12]); day = int(key16[12:14]); rr = int(key16[14:16])
    return f'{yy}{vv}{kai}{format(day,"x")}{rr:02d}'

def parse_se_record(data):
    """SEレコードから上がり3Fを抽出
    JRA-VAN SE（成績）レコード仕様:
    - ヘッダ: 2bytes (SE)
    - データ種別: 1byte
    - レースキー: pos 11-26 (16bytes)
    - 馬番: 各馬のデータブロック内

    SEレコードは1レース分の全馬データを含む
    各馬: 馬番(2) + ... + 上がり3Fタイム(3, /10) + ...
    """
    if len(data) < 30: return []

    rtype = data[:2]
    if rtype != 'SE': return []

    # レースキー
    key16 = data[11:27]
    try:
        jrdb_rid = jravan_key_to_jrdb(key16)
    except:
        return []

    results = []

    # SEレコードの構造を探索
    # JRA-VAN のSEレコードは馬ごとにブロックが並ぶ
    # ブロックサイズは固定長

    # まず全体構造を把握: ヘッダ部分の後に馬データが続く
    # ヘッダ: レコード種別(2) + データ種別(1) + データ作成年月日(8) + レースキー(16) = 27bytes
    # その後にレースヘッダ情報、さらに馬ごとのデータ

    # 馬データの開始位置と1馬あたりのサイズを特定する必要がある
    # JRA-VAN仕様書がないので、データから推定する

    # 簡易パース: 全体から3桁の数値で33.0-42.0の範囲のものを探す
    # (上がり3Fは通常33.0秒〜42.0秒)

    return results

def process_year(jv, year, db):
    """1年分のSEデータを取得"""
    # RACE スペックで SE レコードを取得
    ret = jv.JVOpen('RACE', f'{year}0101000000', 4, 0, 0, '')
    if isinstance(ret, tuple):
        code = ret[0]
        if code == -111:
            print(f'  {year}: no data'); return 0
        if code < 0:
            print(f'  {year}: error {code}'); return 0
        needed = ret[2]
        if needed > 0:
            print(f'  {year}: downloading ({needed} files)...', flush=True)
            t0 = time.time()
            while jv.JVStatus() < needed:
                if time.time() - t0 > 600:
                    print('  timeout'); return 0
                time.sleep(0.5)
    else:
        if ret == -111 or ret < 0: return 0

    # Read SE records
    se_records = {}  # {(race_key, horse_number): last_3f}
    count = 0
    total_read = 0

    for _ in range(10000000):
        try:
            r = jv.JVRead(bytearray(200000), 200000, '')
            if isinstance(r, tuple) and len(r) >= 2:
                rc = r[0]
                if rc == 0: break
                if rc == -1: continue
                if rc > 0:
                    d = r[1]
                    total_read += 1
                    if len(d) > 27:
                        rtype = d[:2]
                        if rtype == 'SE':
                            # Parse SE record
                            key16 = d[11:27]
                            try:
                                ry = int(key16[:4])
                                if ry != year: continue
                                venue = int(key16[8:10])
                                if venue < 1 or venue > 10: continue
                            except: continue

                            jrdb_rid = jravan_key_to_jrdb(key16)

                            # SE record: after header, horse data blocks
                            # Each horse block in SE record:
                            # Find the structure by looking for horse numbers (01-18)
                            # and nearby 3-digit numbers in 330-420 range

                            # JRA-VAN SE record structure (per horse):
                            # The record contains multiple horses
                            # Let's find horse_number and last_3f patterns

                            # Standard JRA-VAN SE format:
                            # Header: ~27 bytes
                            # Race info: ~variable
                            # Horse data: starts at some offset, each horse ~200+ bytes
                            # Within horse block:
                            #   馬番(2) at relative offset
                            #   上がり3F(3) at relative offset (value/10 = seconds)

                            # Since we don't have the exact spec, let's try to find
                            # the pattern by scanning
                            body = d[27:]

                            # Look for 3-char sequences that could be last_3f (/10)
                            # e.g., "345" = 34.5 seconds
                            for pos in range(len(body) - 3):
                                chunk = body[pos:pos+3].strip()
                                if not chunk: continue
                                try:
                                    val = int(chunk)
                                except: continue
                                if 320 <= val <= 420:
                                    # Possible last_3f. Check if nearby is horse_number
                                    # Try various offsets for horse_number relative to this
                                    for hn_offset in [-50, -40, -30, -20, -10, -5, -3, -2]:
                                        hn_pos = pos + hn_offset
                                        if 0 <= hn_pos <= len(body) - 2:
                                            hn_chunk = body[hn_pos:hn_pos+2].strip()
                                            try:
                                                hn_val = int(hn_chunk)
                                                if 1 <= hn_val <= 28:
                                                    # Found a candidate pair
                                                    if count < 5:  # Debug first few
                                                        print(f'    Candidate: rid={jrdb_rid} hn={hn_val} l3f={val/10:.1f} (pos={pos}, hn_off={hn_offset})')
                                                    count += 1
                                            except: pass
            else:
                break
        except Exception as e:
            print(f'  Read error: {e}')
            break

    try: jv.JVClose()
    except: pass

    print(f'  {year}: read {total_read} records, found {count} last_3f candidates', flush=True)
    return count

def main():
    print('=== JRA-VAN Last 3F Download ===')
    print(f'  First: identify SE record structure for 1 year\n')

    jv = create_jv()

    # Just try 2025 to understand the format
    process_year(jv, 2025, None)

    try: jv.JVClose()
    except: pass
    print('\nDone! Check output to understand SE record structure.')

if __name__ == '__main__':
    main()
