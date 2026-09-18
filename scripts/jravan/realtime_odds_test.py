# -*- coding: utf-8 -*-
"""JRA-VAN リアルタイムオッズ取得テスト
レース締切直前に高頻度でオッズを取得し、
何秒前まで取得可能かを検証する。

使い方: 開催日に実行
  py -3.12-32 scripts/jravan/realtime_odds_test.py

結果は data/realtime_test/ に保存。
"""
import os, sys, time, json, sqlite3
from datetime import datetime, timedelta
sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')
SAVE_DIR = os.path.join(BASE, 'data', 'realtime_test')
os.makedirs(SAVE_DIR, exist_ok=True)

def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0: raise RuntimeError(f'JVInit failed: {ret}')
    return jv

def get_today_races(db):
    """今日のレース一覧と発走時刻を取得"""
    today = datetime.now().strftime('%Y-%m-%d')
    rows = db.execute(
        'SELECT race_id, race_date, start_time, venue_name, race_number '
        'FROM races WHERE race_date = ? ORDER BY start_time',
        (today,)
    ).fetchall()
    races = []
    for rid, rd, st, vn, rn in rows:
        if st:
            try:
                h, m = int(st.split(':')[0]), int(st.split(':')[1])
                start_dt = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
                races.append({
                    'race_id': rid, 'start_time': start_dt,
                    'venue': vn, 'race_number': rn, 'start_str': st
                })
            except:
                pass
    return races

def poll_odds(jv, race_key, duration_sec=90, interval_sec=5):
    """指定レースのオッズを高頻度で取得
    発走前duration_sec秒から、interval_sec秒ごとにポーリング
    """
    snapshots = []
    start_time = time.time()

    while time.time() - start_time < duration_sec:
        t0 = time.time()
        try:
            # JVRTOpen for real-time odds (0B31 = 単勝・複勝オッズ)
            ret = jv.JVRTOpen('0B31', race_key)
            if isinstance(ret, tuple):
                code = ret[0]
            else:
                code = ret

            if code < 0:
                snapshots.append({
                    'timestamp': datetime.now().isoformat(),
                    'elapsed': time.time() - start_time,
                    'status': f'error_{code}',
                    'odds': {}
                })
                time.sleep(interval_sec)
                continue

            # Read odds data
            odds = {}
            for _ in range(500):
                try:
                    r = jv.JVRead(bytearray(200000), 200000, '')
                    if isinstance(r, tuple) and len(r) >= 2:
                        rc = r[0]
                        if rc == 0: break
                        if rc == -1: continue
                        if rc > 0:
                            d = r[1]
                            if d and len(d) > 50:
                                # Parse O1 record (単勝オッズ)
                                # pos 43+: 馬ごとに8byte (馬番2 + 単勝4/10 + 人気2)
                                if len(d) > 43:
                                    for pos in range(43, min(len(d), 43 + 28*8), 8):
                                        try:
                                            chunk = d[pos:pos+8]
                                            if len(chunk) >= 8:
                                                hn = int(chunk[0:2])
                                                win_odds = int(chunk[2:6]) / 10.0
                                                pop = int(chunk[6:8])
                                                if 1 <= hn <= 28 and win_odds > 0:
                                                    odds[hn] = {'odds': win_odds, 'pop': pop}
                                        except:
                                            pass
                    else:
                        break
                except:
                    break

            try: jv.JVClose()
            except: pass

            fetch_time = time.time() - t0
            snapshots.append({
                'timestamp': datetime.now().isoformat(),
                'elapsed': time.time() - start_time,
                'fetch_time': fetch_time,
                'status': 'ok',
                'n_horses': len(odds),
                'odds': odds
            })

            now = datetime.now()
            print(f'    {now.strftime("%H:%M:%S.%f")[:12]} | {len(odds):>2} horses | fetch={fetch_time:.2f}s')

        except Exception as e:
            snapshots.append({
                'timestamp': datetime.now().isoformat(),
                'elapsed': time.time() - start_time,
                'status': f'exception: {str(e)}',
                'odds': {}
            })

        # Wait for next poll
        elapsed = time.time() - t0
        wait = max(0, interval_sec - elapsed)
        if wait > 0:
            time.sleep(wait)

    return snapshots

def jrdb_to_jravan_key(race_id, race_date):
    """JRDB race_id → JRA-VAN 16桁キー"""
    yy = race_id[0:2]
    vv = race_id[2:4]
    kk = race_id[4:6]
    rr = race_id[6:8]
    kai = int(kk[0])
    day = int(kk[1], 16)
    yyyy = race_date[:4]
    mm = race_date[5:7]
    dd = race_date[8:10]
    return f'{yyyy}{mm}{dd}{vv}{kai:02d}{day:02d}{int(rr):02d}'

def main():
    print('=== JRA-VAN リアルタイムオッズ取得テスト ===')
    print(f'  現在時刻: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

    # Get today's races
    db = sqlite3.connect(DB_PATH)
    races = get_today_races(db)
    db.close()

    if not races:
        print('\n  今日のレースがDBにありません。')
        print('  開催日に実行してください。')
        print('  （または scripts/import_all.py で今日のレースをインポートしてください）')

        # Show next race dates
        db = sqlite3.connect(DB_PATH)
        future = db.execute(
            "SELECT DISTINCT race_date FROM races WHERE race_date >= ? ORDER BY race_date LIMIT 5",
            (datetime.now().strftime('%Y-%m-%d'),)
        ).fetchall()
        db.close()
        if future:
            print(f'\n  次の開催日: {[r[0] for r in future]}')
        return

    print(f'\n  今日のレース: {len(races)}件')
    for r in races[:5]:
        print(f'    {r["venue"]} {r["race_number"]}R {r["start_str"]} (race_id={r["race_id"]})')
    if len(races) > 5:
        print(f'    ... 他{len(races)-5}件')

    # Find next race (within 10 minutes)
    now = datetime.now()
    next_race = None
    for r in races:
        diff = (r['start_time'] - now).total_seconds()
        if diff > 30:  # At least 30 seconds from now
            next_race = r
            break

    if not next_race:
        print('\n  直近のレースがありません（全レース終了済みか、30秒以内に発走）')
        return

    diff = (next_race['start_time'] - now).total_seconds()
    print(f'\n  次のレース: {next_race["venue"]} {next_race["race_number"]}R')
    print(f'  発走時刻: {next_race["start_str"]}')
    print(f'  あと {diff:.0f}秒 ({diff/60:.1f}分)')

    # Convert race_id to JRA-VAN key
    db = sqlite3.connect(DB_PATH)
    rd = db.execute('SELECT race_date FROM races WHERE race_id=?', (next_race['race_id'],)).fetchone()[0]
    db.close()

    try:
        race_key = jrdb_to_jravan_key(next_race['race_id'], rd)
    except Exception as e:
        print(f'  キー変換エラー: {e}')
        return

    print(f'  JRA-VAN key: {race_key}')

    # Wait until 90 seconds before start
    wait_until = next_race['start_time'] - timedelta(seconds=90)
    wait_sec = (wait_until - datetime.now()).total_seconds()

    if wait_sec > 0:
        print(f'\n  発走90秒前まで {wait_sec:.0f}秒待機...')
        # Poll every 30 seconds while waiting (to show progress)
        while datetime.now() < wait_until:
            remaining = (wait_until - datetime.now()).total_seconds()
            if remaining > 30:
                print(f'    待機中... あと{remaining:.0f}秒')
                time.sleep(min(30, remaining - 1))
            else:
                time.sleep(max(0, remaining))
                break

    # Start high-frequency polling
    print(f'\n  === 高頻度ポーリング開始 ({datetime.now().strftime("%H:%M:%S")}) ===')
    print(f'  発走予定: {next_race["start_str"]}')
    print(f'  3秒間隔でオッズを取得します\n')

    jv = create_jv()
    snapshots = poll_odds(jv, race_key, duration_sec=120, interval_sec=3)

    try: jv.JVClose()
    except: pass

    # Save results
    result = {
        'race_id': next_race['race_id'],
        'race_key': race_key,
        'venue': next_race['venue'],
        'race_number': next_race['race_number'],
        'start_time': next_race['start_str'],
        'test_date': datetime.now().strftime('%Y-%m-%d'),
        'snapshots': snapshots
    }

    save_path = os.path.join(SAVE_DIR, f'rt_test_{next_race["race_id"]}.json')
    with open(save_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'\n  結果保存: {save_path}')

    # Summary
    ok_snaps = [s for s in snapshots if s['status'] == 'ok' and s.get('n_horses', 0) > 0]
    print(f'\n  === 結果 ===')
    print(f'  取得成功: {len(ok_snaps)}/{len(snapshots)} スナップショット')
    if ok_snaps:
        fetch_times = [s['fetch_time'] for s in ok_snaps]
        print(f'  取得時間: 平均{sum(fetch_times)/len(fetch_times):.2f}秒, 最大{max(fetch_times):.2f}秒')
        print(f'  最初のスナップショット: {ok_snaps[0]["timestamp"]}')
        print(f'  最後のスナップショット: {ok_snaps[-1]["timestamp"]}')

        # Compare consecutive snapshots for odds changes
        changes = 0
        for i in range(1, len(ok_snaps)):
            prev = ok_snaps[i-1]['odds']
            curr = ok_snaps[i]['odds']
            for hn in curr:
                if str(hn) in prev or hn in prev:
                    prev_odds = prev.get(hn, prev.get(str(hn), {}))
                    if isinstance(prev_odds, dict) and curr[hn]['odds'] != prev_odds.get('odds', 0):
                        changes += 1
        print(f'  オッズ変動検出: {changes}回')

    print('\n  次のステップ:')
    print('  - 複数レースでテストして、締切何秒前まで取得可能か確認')
    print('  - 取得→予測→投票の全パイプラインの時間を計測')
    print('\nDone!')

if __name__ == '__main__':
    main()
