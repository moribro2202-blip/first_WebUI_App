# -*- coding: utf-8 -*-
"""JRDBの直前情報ページから過去レースの全データをスクレイピング
horse_grid0 の全65カラムを取得してDBに保存する。

使い方:
  python scripts/production/jrdb_scrape_history.py --from 2024-01-01 --to 2024-12-31
  python scripts/production/jrdb_scrape_history.py --resume   # 前回の続きから
"""
import os, sys, re, argparse, sqlite3, time, base64, json
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
sys.stderr.reconfigure(encoding='utf-8', line_buffering=True)
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')

from ipat_voter import load_env


def jrdb_rid_to_url_key(rid):
    yy = rid[0:2]; vv = rid[2:4]; kd = rid[4:6]; rr = rid[6:8]
    return f'{vv}{yy}{kd[0]}{kd[1]}{rr}'


class HttpRateLimitError(Exception):
    """JRDB 402/429 レート制限"""
    pass


def create_context(browser, config):
    """認証済みブラウザコンテキストを作成"""
    user = config.get('JRDB_USER', '')
    pwd = config.get('JRDB_PASS', '')
    auth_str = base64.b64encode(f'{user}:{pwd}'.encode()).decode()
    context = browser.new_context()
    context.set_extra_http_headers({'Authorization': f'Basic {auth_str}'})
    return context


def scrape_race(page, race_date, rid):
    """1レースの全グリッドデータを取得（既存のpageを再利用）"""
    url_key = jrdb_rid_to_url_key(rid)
    date_str = race_date.replace('-', '')
    url = f'https://jrdb.com/member/n_live_{date_str}_{url_key}.html#tabs-0'

    try:
        resp = page.goto(url, timeout=30000, wait_until='networkidle')

        # 402/429検知 — レート制限
        if resp and resp.status in (402, 429):
            raise HttpRateLimitError(f'HTTP {resp.status} for {rid}')

        # その他のHTTPエラー
        if resp and resp.status >= 400:
            print(f'    HTTP {resp.status} for {rid}')
            return None

        # グリッドが描画されるまで待つ
        for _ in range(12):
            time.sleep(2)
            count = page.evaluate('''() => {
                const grid = document.getElementById('horse_grid0');
                if (!grid) return 0;
                return grid.querySelectorAll('tr td[aria-describedby*="umaban"]').length;
            }''')
            if count > 0:
                break

        # horse_grid0 から全データ取得
        data = page.evaluate('''() => {
            const result = [];
            const grid = document.getElementById('horse_grid0');
            if (!grid) return result;
            const rows = grid.querySelectorAll('tr');
            for (const tr of rows) {
                const cells = tr.querySelectorAll('td');
                if (cells.length === 0) continue;
                const row = {};
                for (const td of cells) {
                    const desc = td.getAttribute('aria-describedby') || '';
                    const colName = desc.replace('horse_grid0_', '');
                    row[colName] = td.innerText.trim();
                }
                if (row['umaban']) result.push(row);
            }
            return result;
        }''')

        return data if data else None

    except HttpRateLimitError:
        raise  # 呼び出し元で処理
    except Exception as e:
        print(f'    Error for {rid}: {e}')
        return None


def save_grid_data(rid, race_date, data):
    """グリッドデータをDBに保存（全カラムをJSON + 主要カラムを個別）"""
    db = sqlite3.connect(DB_PATH)
    db.execute('''
        CREATE TABLE IF NOT EXISTS jrdb_live_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id TEXT NOT NULL,
            race_date TEXT NOT NULL,
            horse_number INTEGER NOT NULL,
            horse_name TEXT,
            kehai_code TEXT,
            batai_code TEXT,
            weight INTEGER,
            weight_diff INTEGER,
            tan_odds REAL,
            fuku_odds REAL,
            kij_tan_odds REAL,
            kij_fuku_odds REAL,
            idm_text TEXT,
            idm_juni INTEGER,
            tsogo_sisu INTEGER,
            ten_sisu REAL,
            iti_sisu REAL,
            agari_sisu REAL,
            pace_sisu REAL,
            oikiri_sisu INTEGER,
            shiagari_sisu INTEGER,
            chokyo_ryo TEXT,
            shiagari_henka INTEGER,
            chokyo_arrow INTEGER,
            kyusya_arrow INTEGER,
            chokyo_honsu INTEGER,
            rotation INTEGER,
            blinker TEXT,
            sirusi_padock TEXT,
            sirusi_odds TEXT,
            jk_leading INTEGER,
            tn_leading INTEGER,
            all_data JSON,
            fetched_at TEXT NOT NULL,
            UNIQUE(race_id, horse_number)
        )
    ''')

    now = datetime.now().isoformat()
    count = 0
    for row in data:
        try:
            hn = int(row.get('umaban', '0'))
            if hn < 1:
                continue

            def safe_int(val, default=None):
                if not val or val.strip() in ('', '　', 'null'):
                    return default
                try:
                    return int(re.sub(r'[^\d\-]', '', val))
                except:
                    return default

            def safe_float(val, default=None):
                if not val or val.strip() in ('', '　', 'null'):
                    return default
                try:
                    return float(re.sub(r'[^\d.\-]', '', val))
                except:
                    return default

            zogen = row.get('zogen', row.get('zogendsp', ''))
            zogen = zogen.replace('＋', '+').replace('－', '-').replace('±', '')

            db.execute('''
                INSERT OR REPLACE INTO jrdb_live_data
                (race_id, race_date, horse_number, horse_name,
                 kehai_code, batai_code, weight, weight_diff,
                 tan_odds, fuku_odds, kij_tan_odds, kij_fuku_odds,
                 idm_text, idm_juni, tsogo_sisu,
                 ten_sisu, iti_sisu, agari_sisu, pace_sisu,
                 oikiri_sisu, shiagari_sisu, chokyo_ryo,
                 shiagari_henka, chokyo_arrow, kyusya_arrow,
                 chokyo_honsu, rotation, blinker,
                 sirusi_padock, sirusi_odds,
                 jk_leading, tn_leading,
                 all_data, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ''', (
                rid, race_date, hn,
                row.get('bamei9m', '').strip(),
                row.get('konkehaicd', '').strip(),
                row.get('konbataicd', '').strip(),
                safe_int(row.get('bataiju')),
                safe_int(zogen),
                safe_float(row.get('tanodds')),
                safe_float(row.get('fukodds')),
                safe_float(row.get('kijtanodds')),
                safe_float(row.get('kijfukodds')),
                row.get('idm', '').strip(),
                safe_int(row.get('idmjuni')),
                safe_int(row.get('tsogosisu')),
                safe_float(row.get('tensisu')),
                safe_float(row.get('itisisu')),
                safe_float(row.get('agarisisu')),
                safe_float(row.get('pacesisu')),
                safe_int(row.get('oikirisisu')),
                safe_int(row.get('shiagarisisu')),
                row.get('chokyoryo', '').strip(),
                safe_int(row.get('shiagarihenka')),
                safe_int(row.get('chokyoarrow')),
                safe_int(row.get('kyusyaarrow')),
                safe_int(row.get('chokyohonsu')),
                safe_int(row.get('rotation')),
                row.get('blinkercd', '').strip(),
                row.get('sirusi_padock', '').strip(),
                row.get('sirusi_odds', '').strip(),
                safe_int(row.get('jk_leadingthis')),
                safe_int(row.get('tn_leadingthis')),
                json.dumps(row, ensure_ascii=False),
                now,
            ))
            count += 1
        except Exception as e:
            pass

    db.commit()
    db.close()
    return count


def get_last_scraped_date():
    """最後にスクレイピングした日付を取得"""
    db = sqlite3.connect(DB_PATH)
    try:
        row = db.execute('SELECT MAX(race_date) FROM jrdb_live_data').fetchone()
        return row[0] if row and row[0] else None
    except:
        return None
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description='JRDB過去データスクレイピング')
    parser.add_argument('--from', dest='from_date', default='2024-01-01')
    parser.add_argument('--to', dest='to_date', default='2026-09-13')
    parser.add_argument('--resume', action='store_true', help='前回の続きから')
    parser.add_argument('--limit', type=int, default=0, help='最大レース数（0=無制限）')
    args = parser.parse_args()

    config = load_env()
    if not config or not config.get('JRDB_USER'):
        print("[ERROR] .envにJRDB_USER/JRDB_PASSが必要")
        sys.exit(1)

    from_date = args.from_date
    if args.resume:
        last = get_last_scraped_date()
        if last:
            from_date = last
            print(f'  Resume from: {from_date}')

    # レース一覧を取得
    db = sqlite3.connect(DB_PATH)
    races = db.execute('''
        SELECT race_id, race_date, venue_name, race_number
        FROM races
        WHERE race_date >= ? AND race_date <= ?
        ORDER BY race_date, race_id
    ''', (from_date, args.to_date)).fetchall()

    # 既にスクレイピング済みのレースを除外
    existing = set()
    try:
        for row in db.execute('SELECT DISTINCT race_id FROM jrdb_live_data').fetchall():
            existing.add(row[0])
    except:
        pass
    db.close()

    remaining = [(r[0], r[1], r[2], r[3]) for r in races if r[0] not in existing]
    print(f'Total races: {len(races):,}, Already scraped: {len(existing):,}, Remaining: {len(remaining):,}')

    if args.limit > 0:
        remaining = remaining[:args.limit]
        print(f'Limit: {args.limit}')

    if not remaining:
        print('Nothing to scrape.')
        return

    # ブラウザ起動
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    print(f'Browser started (headless)')

    # コンテキスト・ページを使い回す（毎回作り直さない）
    context = create_context(browser, config)
    page = context.new_page()

    success = 0
    fail = 0
    consecutive_402 = 0
    start_time = time.time()
    BASE_DELAY = 5       # 通常の待機秒数
    MAX_402_WAIT = 600   # 402時の最大待機秒数（10分）

    for i, (rid, rd, vn, rn) in enumerate(remaining):
        label = f'{vn}{rn:>2}R'

        # 進捗表示
        if i > 0 and i % 10 == 0:
            elapsed = time.time() - start_time
            rate = elapsed / i
            eta = rate * (len(remaining) - i)
            print(f'  [{i:>5}/{len(remaining)}] {success} ok, {fail} fail, '
                  f'{rate:.1f}s/race, ETA {eta/60:.0f}min')

        # スクレイピング（リトライ付き）
        data = None
        for attempt in range(3):
            try:
                data = scrape_race(page, rd, rid)
                consecutive_402 = 0  # 成功またはその他エラー → リセット
                if data:
                    break
                time.sleep(2)
            except HttpRateLimitError:
                consecutive_402 += 1
                # 指数バックオフ: 30s, 60s, 120s, 240s, ... 最大600s
                wait = min(30 * (2 ** (consecutive_402 - 1)), MAX_402_WAIT)
                print(f'  [{i}] {label} ({rd}) HTTP 402 (#{consecutive_402}) '
                      f'— waiting {wait}s...')
                time.sleep(wait)

                # 402が5回連続 → コンテキスト再作成（セッションリフレッシュ）
                if consecutive_402 % 5 == 0:
                    print(f'  Refreshing browser context...')
                    try:
                        page.close()
                        context.close()
                    except Exception:
                        pass
                    context = create_context(browser, config)
                    page = context.new_page()

                # 402が10回連続 → ブラウザ再起動
                if consecutive_402 >= 10 and consecutive_402 % 10 == 0:
                    print(f'  Restarting browser...')
                    try:
                        page.close()
                        context.close()
                        browser.close()
                    except Exception:
                        pass
                    browser = pw.chromium.launch(headless=True)
                    context = create_context(browser, config)
                    page = context.new_page()

        if data:
            n = save_grid_data(rid, rd, data)
            success += 1
        else:
            fail += 1
            if fail % 20 == 0:
                print(f'  [{i}] {label} ({rd}) FAIL (total fail: {fail})')

        # 402連続中は既にバックオフで待っているので追加待機なし
        if consecutive_402 == 0:
            time.sleep(BASE_DELAY)

    try:
        page.close()
        context.close()
    except Exception:
        pass
    browser.close()
    pw.stop()

    elapsed = time.time() - start_time
    print(f'\n=== 完了 ===')
    print(f'  成功: {success:,}, 失敗: {fail:,}')
    print(f'  所要時間: {elapsed/60:.1f}分 ({elapsed/max(success+fail,1):.1f}秒/レース)')


if __name__ == '__main__':
    main()
