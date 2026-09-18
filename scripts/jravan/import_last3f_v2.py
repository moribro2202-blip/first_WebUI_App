# -*- coding: utf-8 -*-
"""JRA-VAN SEレコードから上がり3F取得 v2（年フィルタ修正版）
全SEレコードを処理する（年フィルタなし）。
1回のJVOpenで全年分のSEを取得。

py -3.12-32 scripts/jravan/import_last3f_v2.py
"""
import os, sys, time, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')

def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0: raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def jravan_key_to_jrdb(key16):
    yy = key16[2:4]; vv = key16[8:10]
    kai = int(key16[10:12]); day = int(key16[12:14]); rr = int(key16[14:16])
    return f'{yy}{vv}{kai}{format(day,"x")}{rr:02d}'

def main():
    print('=== JRA-VAN Last 3F Import v2 ===')
    db = sqlite3.connect(DB_PATH)

    n_before = db.execute('SELECT COUNT(*) FROM results WHERE last_3f > 0').fetchone()[0]
    print(f'  Before: {n_before:,} rows with last_3f')

    jv = create_jv()

    # Open from 2015 to get all historical SE records
    ret = jv.JVOpen('RACE', '20150101000000', 4, 0, 0, '')
    if isinstance(ret, tuple):
        code = ret[0]
        print(f'  JVOpen code: {code}')
        if code < 0:
            print(f'  Error: {code}'); return
        needed = ret[2]
        if needed > 0:
            print(f'  Downloading {needed} files...', flush=True)
            t0 = time.time()
            while jv.JVStatus() < needed:
                if time.time() - t0 > 600:
                    print('  Timeout'); break
                time.sleep(0.5)

    count = 0; total_se = 0; skipped = 0; errors = 0
    batch = 0

    for _ in range(10000000):
        try:
            r = jv.JVRead(bytearray(200000), 200000, '')
            if isinstance(r, tuple) and len(r) >= 2:
                rc = r[0]
                if rc == 0: break
                if rc == -1: continue
                if rc > 0:
                    d = r[1]
                    if len(d) > 271 and d[:2] == 'SE':
                        total_se += 1

                        key16 = d[11:27]
                        try:
                            venue = int(key16[8:10])
                            if venue < 1 or venue > 10:
                                skipped += 1; continue
                        except:
                            skipped += 1; continue

                        try:
                            jrdb_rid = jravan_key_to_jrdb(key16)
                        except:
                            skipped += 1; continue

                        try:
                            hn = int(d[28:30])
                        except:
                            skipped += 1; continue
                        if hn < 1 or hn > 28:
                            skipped += 1; continue

                        try:
                            l3f_raw = int(d[268:271])
                            if l3f_raw < 280 or l3f_raw > 500:
                                skipped += 1; continue
                            l3f = l3f_raw / 10.0
                        except:
                            errors += 1; continue

                        db.execute('UPDATE results SET last_3f=? WHERE race_id=? AND horse_number=?',
                                   (l3f, jrdb_rid, hn))
                        count += 1
                        batch += 1

                        if batch >= 10000:
                            db.commit()
                            batch = 0
                            if count % 50000 == 0:
                                print(f'    {count:,} updated (SE total: {total_se:,})...', flush=True)
            else:
                break
        except Exception as e:
            print(f'  Read error: {e}')
            break

    db.commit()
    try: jv.JVClose()
    except: pass

    n_after = db.execute('SELECT COUNT(*) FROM results WHERE last_3f > 0').fetchone()[0]
    print(f'\n  SE records processed: {total_se:,}')
    print(f'  Updated: {count:,}')
    print(f'  Skipped: {skipped:,}')
    print(f'  Errors: {errors:,}')
    print(f'  Before: {n_before:,} → After: {n_after:,} (+{n_after-n_before:,})')

    # Stats by year
    print('\n  By year:')
    for yr in range(2015, 2027):
        n = db.execute(f"SELECT COUNT(*) FROM results r JOIN races ra ON r.race_id=ra.race_id WHERE r.last_3f > 0 AND ra.race_date >= '{yr}-01-01' AND ra.race_date < '{yr+1}-01-01'").fetchone()[0]
        t = db.execute(f"SELECT COUNT(*) FROM results r JOIN races ra ON r.race_id=ra.race_id WHERE ra.race_date >= '{yr}-01-01' AND ra.race_date < '{yr+1}-01-01'").fetchone()[0]
        pct = n/t*100 if t > 0 else 0
        print(f'    {yr}: {n:,}/{t:,} ({pct:.0f}%)')

    db.close()
    print('Done!')

if __name__ == '__main__':
    main()
