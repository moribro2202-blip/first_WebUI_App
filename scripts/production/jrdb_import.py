# -*- coding: utf-8 -*-
"""JRDB自動ダウンロード+インポート
指定日のBAC/KYI/OZをJRDBサイトからダウンロードしてDBにインポートする。

使い方:
  python scripts/production/jrdb_import.py              # 明日のデータ
  python scripts/production/jrdb_import.py --date 260912  # 日付指定
  python scripts/production/jrdb_import.py --today        # 今日のデータ
"""
import os, sys, zipfile, sqlite3, glob, argparse, io
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
JRDB_DIR = os.path.join(BASE, 'data', 'jrdb')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ipat_voter import load_env

VENUE = {'01':'札幌','02':'函館','03':'福島','04':'新潟','05':'東京','06':'中山','07':'中京','08':'京都','09':'阪神','10':'小倉'}
TRACK = {'11':'良','12':'稍重','13':'重','14':'不良','21':'良','22':'稍重','23':'重','24':'不良'}
WEATHER = {'1':'晴','2':'曇','3':'雨','4':'小雨','5':'小雪','6':'雪'}
RUN_STYLES = {'1':'逃げ','2':'先行','3':'差し','4':'追込','5':'好位差し','6':'自在','7':'後方'}

# JRDBデータタイプ → フォルダ名
JRDB_FOLDERS = {
    'BAC': 'Bac',
    'KYI': 'Kyi',
    'OZ':  'Oz',
    'CYB': 'Cyb',
}


def download_jrdb_file(session, prefix, date_str):
    """JRDBからZIPファイルをダウンロード

    Args:
        session: requests.Session (認証済み)
        prefix: 'BAC', 'KYI', 'OZ'
        date_str: '260912' (YYMMDD)

    Returns:
        bytes or None
    """
    folder = JRDB_FOLDERS[prefix]
    yy = date_str[:2]
    year = f'20{yy}'
    filename = f'{prefix}{date_str}.zip'
    url = f'http://www.jrdb.com/member/datazip/{folder}/{year}/{filename}'

    print(f"  DL: {url} ...", end='', flush=True)
    r = session.get(url, timeout=30)
    if r.status_code == 200 and len(r.content) > 100:
        print(f" OK ({len(r.content):,} bytes)")
        return r.content
    else:
        print(f" FAIL (status={r.status_code})")
        return None


def extract_zip(zip_bytes, prefix):
    """ZIPを解凍してdata/jrdb/{prefix}/に保存"""
    target_dir = os.path.join(JRDB_DIR, prefix)
    os.makedirs(target_dir, exist_ok=True)
    count = 0
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith('.txt'):
                out_path = os.path.join(target_dir, os.path.basename(name))
                with open(out_path, 'wb') as f:
                    f.write(zf.read(name))
                count += 1
    return count


def import_bac(db, date_str):
    """BACファイルをDBにインポート"""
    pattern = os.path.join(JRDB_DIR, 'BAC', f'BAC{date_str}*.txt')
    count = 0
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath, 'rb') as f:
            for line in f.readlines():
                if len(line) < 26: continue
                v = line[0:2].decode('ascii', 'replace').strip()
                y = line[2:4].decode('ascii', 'replace').strip()
                k = line[4:6].decode('ascii', 'replace').strip()
                rn = line[6:8].decode('ascii', 'replace').strip()
                if not v or not y: continue
                rid = f'{y}{v}{k}{rn}'
                dr = line[8:16].decode('ascii', 'replace').strip()
                rd = f'{dr[:4]}-{dr[4:6]}-{dr[6:8]}'
                dist = int(line[20:24].decode('ascii', 'replace').strip() or '0')
                sf = {'1': '芝', '2': 'ダート', '3': '障害'}.get(line[24:25].decode('ascii', 'replace'), '?')
                di = {'1': '右', '2': '左', '3': '直線'}.get(line[25:26].decode('ascii', 'replace'), '右')
                tc = TRACK.get(line[26:28].decode('ascii', 'replace').strip())
                w = WEATHER.get(line[28:29].decode('ascii', 'replace').strip())
                syubetsu = line[29:31].decode('ascii', 'replace').strip()
                try:
                    nm = line[35:85].decode('shift_jis', 'ignore').strip().replace('\u3000', ' ').strip()
                except:
                    nm = None
                grade = None
                if nm and nm[0].isdigit():
                    gc = nm[0]; nm = nm[1:].strip()
                    grade = {'1': 'G1', '2': 'G2', '3': 'G3'}.get(gc, 'OP' if syubetsu == 'OP' else None)
                elif syubetsu == 'OP':
                    grade = 'OP'
                tr = line[16:20].decode('ascii', 'replace').strip()
                st = f'{tr[:2]}:{tr[2:]}' if len(tr) == 4 else None
                db.execute(
                    'INSERT OR REPLACE INTO races (race_id,race_date,venue_code,venue_name,race_number,distance,surface,start_time,course_direction,track_condition,weather,race_name,grade) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (rid, rd, v, VENUE.get(v, v), int(rn), dist, sf, st, di, tc, w, nm or None, grade))
                count += 1
    db.commit()
    return count


def import_kyi(db, date_str):
    """KYIファイルをDBにインポート"""
    pattern = os.path.join(JRDB_DIR, 'KYI', f'KYI{date_str}*.txt')
    count = 0
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath, 'rb') as f:
            for line in f.readlines():
                if len(line) < 200: continue
                v = line[0:2].decode('ascii', 'replace').strip()
                y = line[2:4].decode('ascii', 'replace').strip()
                k = line[4:6].decode('ascii', 'replace').strip()
                rn = line[6:8].decode('ascii', 'replace').strip()
                hn = line[8:10].decode('ascii', 'replace').strip()
                if not v or not y or not hn: continue
                try: hn_i = int(hn)
                except: continue
                rid = f'{y}{v}{k}{rn}'
                hid = line[10:18].decode('ascii', 'replace').strip()
                try: hname = line[18:48].decode('shift_jis', 'ignore').strip()
                except: hname = ''
                try: jockey = line[171:183].decode('shift_jis', 'ignore').strip()
                except: jockey = ''
                try: trainer = line[187:199].decode('shift_jis', 'ignore').strip()
                except: trainer = ''
                try: cw = int(line[183:186].decode('ascii', 'replace').strip()) / 10
                except: cw = 0
                try: idm = float(line[54:59].decode('ascii', 'replace').strip())
                except: idm = None
                try: rider = float(line[59:64].decode('ascii', 'replace').strip())
                except: rider = None
                try: total = float(line[74:79].decode('ascii', 'replace').strip())
                except: total = None
                rs = RUN_STYLES.get(line[85:86].decode('ascii', 'replace').strip())
                da = line[80:81].decode('ascii', 'replace').strip()
                db.execute(
                    'INSERT OR REPLACE INTO entries (race_id,horse_number,horse_id,horse_name,jockey_name,trainer_name,carried_weight,idm,rider_index,total_index,run_style,distance_aptitude) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (rid, hn_i, hid, hname, jockey, trainer, cw, idm, rider, total, rs, da))
                count += 1
    db.commit()
    return count


def import_oz(db, date_str):
    """OZファイル（前日単勝オッズ）をDBにインポート"""
    pattern = os.path.join(JRDB_DIR, 'OZ', f'OZ{date_str}*.txt')
    count = 0
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath, 'rb') as f:
            for line in f.readlines():
                if len(line) < 100: continue
                v = line[0:2].decode('ascii', 'replace').strip()
                y = line[2:4].decode('ascii', 'replace').strip()
                k = line[4:6].decode('ascii', 'replace').strip()
                rn = line[6:8].decode('ascii', 'replace').strip()
                rid = f'{y}{v}{k}{rn}'
                try: heads = int(line[8:10].decode('ascii', 'replace').strip())
                except: heads = 18
                for i in range(min(heads, 18)):
                    s = line[10 + i * 5:15 + i * 5].decode('ascii', 'replace').strip()
                    try:
                        o = float(s)
                        if o > 0:
                            db.execute('INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)',
                                       (rid, 'win', str(i + 1), o))
                            count += 1
                    except:
                        pass
    db.commit()
    return count


def main():
    parser = argparse.ArgumentParser(description='JRDB自動ダウンロード+インポート')
    parser.add_argument('--date', help='日付 YYMMDD (例: 260912)')
    parser.add_argument('--today', action='store_true', help='今日のデータ')
    args = parser.parse_args()

    # 日付決定
    if args.date:
        date_str = args.date
    elif args.today:
        date_str = datetime.now().strftime('%y%m%d')
    else:
        # デフォルト: 明日（土日なら当日）
        now = datetime.now()
        wd = now.weekday()
        if wd in (5, 6):  # 土日 → 当日
            date_str = now.strftime('%y%m%d')
        else:
            # 次の土曜
            days_until_sat = (5 - wd) % 7
            if days_until_sat == 0:
                days_until_sat = 7
            target = now + timedelta(days=days_until_sat)
            date_str = target.strftime('%y%m%d')

    print(f"=" * 50)
    print(f"=== JRDB自動インポート: {date_str} ===")
    print(f"=" * 50)

    # 認証情報
    config = load_env()
    if not config:
        sys.exit(1)
    jrdb_user = config.get('JRDB_USER', '')
    jrdb_pass = config.get('JRDB_PASS', '')
    if not jrdb_user or not jrdb_pass:
        print("  [ERROR] .envにJRDB_USER/JRDB_PASSが設定されていません")
        sys.exit(1)

    import requests
    session = requests.Session()
    session.auth = (jrdb_user, jrdb_pass)

    # ダウンロード
    print("\n--- ダウンロード ---")
    downloaded = {}
    for prefix in ['BAC', 'KYI', 'OZ', 'CYB']:
        data = download_jrdb_file(session, prefix, date_str)
        if data:
            count = extract_zip(data, prefix)
            downloaded[prefix] = count
            print(f"    {prefix}: {count} files extracted")
        else:
            print(f"    {prefix}: ダウンロード失敗")

    if not downloaded:
        print("\n  データが1つもダウンロードできませんでした。")
        print("  JRDBにまだアップロードされていない可能性があります。")
        sys.exit(1)

    # インポート
    print("\n--- DBインポート ---")
    db = sqlite3.connect(DB_PATH, timeout=60)
    db.execute('PRAGMA busy_timeout=60000')

    if 'BAC' in downloaded:
        n = import_bac(db, date_str)
        print(f"  BAC: {n} races")

    if 'KYI' in downloaded:
        n = import_kyi(db, date_str)
        print(f"  KYI: {n} entries")

    if 'OZ' in downloaded:
        n = import_oz(db, date_str)
        print(f"  OZ: {n} win odds")

    # 確認
    print("\n--- 確認 ---")
    yy = date_str[:2]
    mm = date_str[2:4]
    dd = date_str[4:6]
    race_date = f'20{yy}-{mm}-{dd}'

    races = db.execute('SELECT COUNT(*) FROM races WHERE race_date=?', (race_date,)).fetchone()[0]
    entries = db.execute('SELECT COUNT(*) FROM entries WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?)', (race_date,)).fetchone()[0]
    odds = db.execute('SELECT COUNT(*) FROM odds WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?) AND bet_type="win"', (race_date,)).fetchone()[0]

    print(f"  日付: {race_date}")
    print(f"  レース: {races}R")
    print(f"  エントリー: {entries}頭")
    print(f"  前日オッズ: {odds}件")

    if races > 0 and entries > 0:
        # レース一覧表示
        for row in db.execute(
            'SELECT venue_name, race_number, surface, distance, race_name, grade '
            'FROM races WHERE race_date=? ORDER BY venue_code, race_number', (race_date,)
        ).fetchall():
            vn, rn, sf, dist, nm, gr = row
            gr_str = f' [{gr}]' if gr else ''
            print(f"    {vn}{rn:>2}R {sf}{dist}m {nm or ''}{gr_str}")
        print(f"\n  ✅ run_now.py でEV計算可能です")
    else:
        print(f"\n  ❌ データ不足")

    db.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
