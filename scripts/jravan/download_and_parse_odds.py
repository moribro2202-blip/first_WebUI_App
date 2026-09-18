# -*- coding: utf-8 -*-
"""JRA-VAN全組合せ確定オッズ取得＆DB格納（32bit Python専用）
RACEスペックからO1-O6レコードを取得し、全券種の確定オッズをSQLiteに格納。
年別レジューム対応。

使い方: py -3.12-32 scripts/jravan/download_and_parse_odds.py
"""
import json, os, sys, time, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
PROGRESS_FILE = os.path.join(BASE, 'data', 'jravan_odds_progress.json')
START_YEAR = 2015
END_YEAR = 2026

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

def parse_blocks(data, header_len=40):
    body = data[header_len:]
    blocks = []; cur = []
    for c in body:
        if c == ' ':
            if cur: blocks.append(''.join(cur)); cur = []
        else: cur.append(c)
    if cur: blocks.append(''.join(cur))
    return blocks

def parse_o2_umaren(data):
    """O2 馬連: combo(4)+odds(6,/10)+pop(3)=13"""
    blocks = parse_blocks(data)
    results = []
    for block in blocks:
        for i in range(len(block) // 13):
            e = block[i*13:(i+1)*13]
            if len(e) < 13: continue
            try:
                h1 = int(e[0:2]); h2 = int(e[2:4])
                odds = int(e[4:10]) / 10.0; pop = int(e[10:13])
                if h1 > 0 and h2 > 0 and odds > 0:
                    combo = '-'.join(str(x) for x in sorted([h1, h2]))
                    results.append(('umaren', combo, odds, pop))
            except: pass
    return results

def parse_o3_wide(data):
    """O3 ワイド: combo(4)+min(5,/10)+max(5,/10)+pop(3)=17"""
    blocks = parse_blocks(data)
    results = []
    for block in blocks:
        for i in range(len(block) // 17):
            e = block[i*17:(i+1)*17]
            if len(e) < 17: continue
            try:
                h1 = int(e[0:2]); h2 = int(e[2:4])
                omin = int(e[4:9]) / 10.0; omax = int(e[9:14]) / 10.0; pop = int(e[14:17])
                if h1 > 0 and h2 > 0 and omin > 0:
                    combo = '-'.join(str(x) for x in sorted([h1, h2]))
                    results.append(('wide', combo, omin, pop, omax))
            except: pass
    return results

def parse_o4_umatan(data):
    """O4 馬単: combo(4)+odds(6,/10)+pop(3)=13"""
    blocks = parse_blocks(data)
    results = []
    for block in blocks:
        for i in range(len(block) // 13):
            e = block[i*13:(i+1)*13]
            if len(e) < 13: continue
            try:
                h1 = int(e[0:2]); h2 = int(e[2:4])
                odds = int(e[4:10]) / 10.0; pop = int(e[10:13])
                if h1 > 0 and h2 > 0 and odds > 0:
                    combo = f'{h1}-{h2}'
                    results.append(('umatan', combo, odds, pop))
            except: pass
    return results

def parse_o5_trio(data):
    """O5 三連複: combo(6)+odds(6,/10)+pop(3)=15"""
    blocks = parse_blocks(data)
    results = []
    for block in blocks:
        for i in range(len(block) // 15):
            e = block[i*15:(i+1)*15]
            if len(e) < 15: continue
            try:
                h1 = int(e[0:2]); h2 = int(e[2:4]); h3 = int(e[4:6])
                odds = int(e[6:12]) / 10.0; pop = int(e[12:15])
                if h1 > 0 and h2 > 0 and h3 > 0 and odds > 0:
                    combo = '-'.join(str(x) for x in sorted([h1, h2, h3]))
                    results.append(('sanrenpuku', combo, odds, pop))
            except: pass
    return results

def parse_o6_trifecta(data):
    """O6 三連単: combo(6)+odds(7,/10)+pop(4)=17"""
    blocks = parse_blocks(data)
    results = []
    for block in blocks:
        for i in range(len(block) // 17):
            e = block[i*17:(i+1)*17]
            if len(e) < 17: continue
            try:
                h1 = int(e[0:2]); h2 = int(e[2:4]); h3 = int(e[4:6])
                odds = int(e[6:13]) / 10.0; pop = int(e[13:17])
                if h1 > 0 and h2 > 0 and h3 > 0 and odds > 0:
                    combo = f'{h1}-{h2}-{h3}'
                    results.append(('sanrentan', combo, odds, pop))
            except: pass
    return results

PARSERS = {'O2': parse_o2_umaren, 'O3': parse_o3_wide, 'O4': parse_o4_umatan,
           'O5': parse_o5_trio, 'O6': parse_o6_trifecta}

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try: return json.load(open(PROGRESS_FILE, encoding='utf-8'))
        except: pass
    return {'done_years': []}

def save_progress(prog):
    json.dump(prog, open(PROGRESS_FILE, 'w', encoding='utf-8'), indent=2)

def process_year(jv, year, db):
    """1年分のRACEスペックからO2-O6を取得してDBに格納"""
    ret = jv.JVOpen('RACE', f'{year}0101000000', 4, 0, 0, '')
    if isinstance(ret, tuple):
        code = ret[0]
        if code == -111:
            print(f'  {year}: no data'); return True
        if code < 0:
            print(f'  {year}: error {code}'); return False
        needed = ret[2]
        if needed > 0:
            print(f'  {year}: downloading ({needed} files)...', flush=True)
            t0 = time.time()
            while jv.JVStatus() < needed:
                if time.time() - t0 > 600: print('  timeout'); return False
                time.sleep(0.5)
    else:
        if ret == -111: print(f'  {year}: no data'); return True
        if ret < 0: print(f'  {year}: error {ret}'); return False

    # Read all O2-O6 records
    race_odds = {}  # {race_key: {O2: data, O3: data, ...}}
    count = 0
    for _ in range(5000000):
        try:
            r = jv.JVRead(bytearray(200000), 200000, '')
            if isinstance(r, tuple) and len(r) >= 2:
                rc = r[0]
                if rc == 0: break
                if rc == -1: continue
                if rc > 0:
                    d = r[1]
                    if len(d) > 27:
                        rtype = d[:2]
                        if rtype in PARSERS:
                            key16 = d[11:27]
                            # Check year matches
                            try:
                                ry = int(key16[:4])
                                if ry != year: continue
                            except: continue
                            # Verify central venue (01-10)
                            try:
                                venue = int(key16[8:10])
                                if venue < 1 or venue > 10: continue
                            except: continue
                            if key16 not in race_odds:
                                race_odds[key16] = {}
                            race_odds[key16][rtype] = d
                            count += 1
            else:
                break
        except Exception as e:
            print(f'  Read error: {e}')
            break

    try: jv.JVClose()
    except: pass

    print(f'  {year}: {count} O-records from {len(race_odds)} races', flush=True)

    # Parse and insert
    total_inserts = 0
    for key16, odds_data in race_odds.items():
        jrdb_rid = jravan_key_to_jrdb(key16)

        for rtype, data in odds_data.items():
            parser = PARSERS[rtype]
            entries = parser(data)
            for entry in entries:
                if len(entry) == 4:
                    bt, combo, odds, pop = entry
                    db.execute('INSERT OR REPLACE INTO confirmed_odds (race_id,bet_type,combination,odds,popularity) VALUES (?,?,?,?,?)',
                               (jrdb_rid, bt, combo, odds, pop))
                elif len(entry) == 5:
                    bt, combo, odds, pop, omax = entry
                    db.execute('INSERT OR REPLACE INTO confirmed_odds (race_id,bet_type,combination,odds,popularity,odds_max) VALUES (?,?,?,?,?,?)',
                               (jrdb_rid, bt, combo, odds, pop, omax))
                total_inserts += 1

    db.commit()
    print(f'  {year}: {total_inserts:,} odds inserted', flush=True)
    return True

def main():
    print('=== JRA-VAN All-Combo Confirmed Odds Download ===')

    # Create table
    db = sqlite3.connect(DB_PATH)
    db.execute('''CREATE TABLE IF NOT EXISTS confirmed_odds (
        race_id TEXT,
        bet_type TEXT,
        combination TEXT,
        odds REAL,
        popularity INTEGER,
        odds_max REAL,
        PRIMARY KEY (race_id, bet_type, combination)
    )''')
    db.commit()

    prog = load_progress()
    done = set(prog['done_years'])
    print(f'Done years: {sorted(done)}')

    jv = create_jv()
    batch = 0

    for year in range(END_YEAR, START_YEAR - 1, -1):
        if year in done:
            print(f'  {year}: skip (done)')
            continue

        ok = process_year(jv, year, db)
        if ok:
            done.add(year)
            prog['done_years'] = sorted(done)
            save_progress(prog)
        else:
            print(f'  {year}: FAILED, will retry next run')

        batch += 1
        if batch % 3 == 0:
            try: jv.JVClose()
            except: pass
            del jv; time.sleep(1)
            jv = create_jv()

    try: jv.JVClose()
    except: pass

    # Summary
    print(f'\n=== Summary ===')
    for bt in ['umaren','wide','umatan','sanrenpuku','sanrentan']:
        n = db.execute(f'SELECT COUNT(*) FROM confirmed_odds WHERE bet_type=?',(bt,)).fetchone()[0]
        nr = db.execute(f'SELECT COUNT(DISTINCT race_id) FROM confirmed_odds WHERE bet_type=?',(bt,)).fetchone()[0]
        print(f'  {bt}: {n:,} combos, {nr:,} races')
    db.close()
    print('Done!')

if __name__ == '__main__':
    main()
