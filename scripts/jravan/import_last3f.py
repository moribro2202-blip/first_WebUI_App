# -*- coding: utf-8 -*-
"""JRA-VAN SEレコードから上がり3Fを取得してDBに格納
SEレコード pos 268-271 (3桁, /10 = 秒)
馬番: pos 27-29 (2桁)

py -3.12-32 scripts/jravan/import_last3f.py
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

def process_year(jv, year, db):
    ret = jv.JVOpen('RACE', f'{year}0101000000', 4, 0, 0, '')
    if isinstance(ret, tuple):
        code = ret[0]
        if code == -111: print(f'  {year}: no data'); return 0
        if code < 0: print(f'  {year}: error {code}'); return 0
        needed = ret[2]
        if needed > 0:
            print(f'  {year}: downloading ({needed} files)...', flush=True)
            t0 = time.time()
            while jv.JVStatus() < needed:
                if time.time() - t0 > 600: print('  timeout'); return 0
                time.sleep(0.5)
    else:
        if ret == -111 or ret < 0: return 0

    count = 0
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
                        key16 = d[11:27]
                        try:
                            ry = int(key16[:4])
                            if ry != year: continue
                            venue = int(key16[8:10])
                            if venue < 1 or venue > 10: continue
                        except: continue

                        jrdb_rid = jravan_key_to_jrdb(key16)

                        # Horse number: pos 27-29
                        try: hn = int(d[27:29])
                        except: continue
                        if hn < 1 or hn > 28: continue

                        # Last 3F: pos 268-271
                        try:
                            l3f_raw = int(d[268:271])
                            if l3f_raw < 300 or l3f_raw > 450: continue
                            l3f = l3f_raw / 10.0
                        except: continue

                        db.execute('UPDATE results SET last_3f=? WHERE race_id=? AND horse_number=?',
                                   (l3f, jrdb_rid, hn))
                        count += 1
            else: break
        except Exception as e:
            print(f'  Read error: {e}')
            break

    try: jv.JVClose()
    except: pass
    db.commit()
    return count

def main():
    print('=== JRA-VAN Last 3F Import ===')
    db = sqlite3.connect(DB_PATH)

    # Check current state
    n_before = db.execute('SELECT COUNT(*) FROM results WHERE last_3f IS NOT NULL AND last_3f > 0').fetchone()[0]
    print(f'  Before: {n_before:,} rows with last_3f')

    jv = create_jv()
    total = 0

    for year in range(2026, 2014, -1):  # Recent first
        n = process_year(jv, year, db)
        total += n
        print(f'  {year}: {n:,} updated', flush=True)

        # Reconnect every 3 years
        if year % 3 == 0:
            try: jv.JVClose()
            except: pass
            del jv; time.sleep(1)
            jv = create_jv()

    try: jv.JVClose()
    except: pass

    n_after = db.execute('SELECT COUNT(*) FROM results WHERE last_3f IS NOT NULL AND last_3f > 0').fetchone()[0]
    print(f'\n  After: {n_after:,} rows with last_3f (+{n_after-n_before:,})')

    # Verify
    print('\n  Sample:')
    for r in db.execute('SELECT race_id, horse_number, finish_position, last_3f FROM results WHERE last_3f > 0 ORDER BY race_id DESC LIMIT 10').fetchall():
        print(f'    rid={r[0]} hn={r[1]} fp={r[2]} l3f={r[3]}')

    # Stats by year
    print('\n  By year:')
    for yr in range(2015, 2027):
        n = db.execute(f"SELECT COUNT(*) FROM results r JOIN races ra ON r.race_id=ra.race_id WHERE r.last_3f > 0 AND ra.race_date >= '{yr}-01-01' AND ra.race_date < '{yr+1}-01-01'").fetchone()[0]
        print(f'    {yr}: {n:,}')

    db.close()
    print(f'\n  Total updated: {total:,}')
    print('Done!')

if __name__ == '__main__':
    main()
