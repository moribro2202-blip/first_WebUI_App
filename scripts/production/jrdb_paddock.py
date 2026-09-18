# -*- coding: utf-8 -*-
"""JRDBの直前情報ページからパドック気配・馬体重をスクレイピング（Playwright版）

tabs-1（直前情報）のhorse_grid1から以下を取得:
- konkehaicd: 今回気配コード（平凡/チャカ/不安定/気合乗り等）
- bataiju: 馬体重
- zogen: 体重増減
- tanodds/fukodds: 単勝/複勝オッズ
- idm: IDM+印

使い方:
  python scripts/production/jrdb_paddock.py --race 26094401    # 指定レース
  python scripts/production/jrdb_paddock.py --today             # 本日全レース
  python scripts/production/jrdb_paddock.py --test              # 最新レースでテスト
  python scripts/production/jrdb_paddock.py --visible           # ブラウザ表示
"""
import os, sys, re, argparse, sqlite3, time, base64
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, 'data', 'jrdb.db')

from ipat_voter import load_env

# 気配コード → 数値マッピング（バックテスト用）
KEHAI_MAP = {
    'イレ込': 1, 'イレ込む': 1,
    'チャカ': 2, 'チャカつく': 2,
    '落着なし': 3, '落ち着きなし': 3,
    'やや落着なし': 4,
    '平凡': 5, '普通': 5,
    'やや気合': 6,
    '気合乗り': 7, '気合良': 7,
    '気合十分': 8,
    '気合抜群': 9,
    '不安定': 3,  # 不安定はやや悪い寄り
    '': 0, '　': 0,
}


def jrdb_rid_to_url_key(rid):
    """JRDB race_id (e.g. 26094401) → URL用キー (e.g. 09264401)"""
    yy = rid[0:2]; vv = rid[2:4]; kd = rid[4:6]; rr = rid[6:8]
    return f'{vv}{yy}{kd[0]}{kd[1]}{rr}'


class JRDBPaddockScraper:
    """JRDB直前情報ページのスクレイパー"""

    def __init__(self, headless=True):
        self.config = load_env()
        self.headless = headless
        self.browser = None
        self.page = None

    def start(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context()
        user = self.config.get('JRDB_USER', '')
        pwd = self.config.get('JRDB_PASS', '')
        auth = base64.b64encode(f'{user}:{pwd}'.encode()).decode()
        self.context.set_extra_http_headers({'Authorization': f'Basic {auth}'})
        self.page = self.context.new_page()
        print(f'  [JRDB] ブラウザ起動 (headless={self.headless})')

    def _new_context(self):
        """新しいブラウザコンテキストを作成（認証ヘッダー付き）"""
        if self.page:
            try: self.page.close()
            except: pass
        if self.context:
            try: self.context.close()
            except: pass
        user = self.config.get('JRDB_USER', '')
        pwd = self.config.get('JRDB_PASS', '')
        auth_str = base64.b64encode(f'{user}:{pwd}'.encode()).decode()
        self.context = self.browser.new_context()
        self.context.set_extra_http_headers({'Authorization': f'Basic {auth_str}'})
        self.page = self.context.new_page()

    def _load_grid(self, url):
        """ページを開いてグリッドデータを取得（1回の試行）"""
        self._new_context()
        self.page.goto(url, timeout=30000, wait_until='networkidle')
        # SPAの初期化を待つ
        time.sleep(5)

        # グリッドが描画されるまで待つ（最大40秒）
        for _ in range(20):
            time.sleep(2)
            count = self.page.evaluate('''() => {
                const grid = document.getElementById('horse_grid1');
                if (!grid) return 0;
                return grid.querySelectorAll('tr td[aria-describedby*="umaban"]').length;
            }''')
            if count > 0:
                break

        # horse_grid1からデータ取得
        return self.page.evaluate('''() => {
            const result = [];
            const grid = document.getElementById('horse_grid1');
            if (!grid) return result;
            const rows = grid.querySelectorAll('tr');
            for (const tr of rows) {
                const cells = tr.querySelectorAll('td');
                if (cells.length === 0) continue;
                const row = {};
                for (const td of cells) {
                    const desc = td.getAttribute('aria-describedby') || '';
                    const colName = desc.replace('horse_grid1_', '');
                    row[colName] = td.innerText.trim();
                }
                if (row['umaban']) result.push(row);
            }
            return result;
        }''')

    def fetch_race(self, race_date, rid, max_retries=2):
        """直前情報ページからデータを取得（リトライ付き）

        Returns:
            list of dict or None
        """
        if not self.browser:
            self.start()

        url_key = jrdb_rid_to_url_key(rid)
        date_str = race_date.replace('-', '')
        url = f'https://jrdb.com/member/n_live_{date_str}_{url_key}.html#tabs-1'

        raw_data = None
        for attempt in range(max_retries + 1):
            try:
                raw_data = self._load_grid(url)
                if raw_data:
                    break
                if attempt < max_retries:
                    time.sleep(5)  # 429対策: リトライ間隔5秒
            except Exception as e:
                if attempt < max_retries:
                    time.sleep(5)  # 429対策
                else:
                    print(f'  [JRDB] Error after {max_retries + 1} attempts: {e}')
                    return None

        try:
            if not raw_data:
                return None

            # パース
            results = []
            for row in raw_data:
                entry = {}
                try:
                    entry['horse_number'] = int(row.get('umaban', '0'))
                except:
                    continue
                if entry['horse_number'] < 1:
                    continue

                entry['horse_name'] = row.get('bamei9m', '').strip()

                # 気配コード
                kehai_raw = row.get('konkehaicd', '').strip()
                entry['kehai_text'] = kehai_raw
                entry['kehai_code'] = KEHAI_MAP.get(kehai_raw, 0)

                # 馬体コード
                entry['batai_text'] = row.get('konbataicd', '').strip()

                # パドック印
                entry['paddock_sirusi'] = row.get('sirusi_padock', '').strip()

                # 馬体重
                try:
                    entry['weight'] = int(row.get('bataiju', '0'))
                except:
                    entry['weight'] = None

                # 増減
                zogen = row.get('zogen', row.get('zogendsp', '')).strip()
                zogen = zogen.replace('＋', '+').replace('－', '-').replace('±', '')
                try:
                    entry['weight_diff'] = int(zogen)
                except:
                    entry['weight_diff'] = 0

                # オッズ
                try:
                    entry['tan_odds'] = float(row.get('tanodds', '0'))
                except:
                    entry['tan_odds'] = None
                try:
                    entry['fuku_odds'] = float(row.get('fukodds', '0'))
                except:
                    entry['fuku_odds'] = None

                # IDM
                entry['idm_text'] = row.get('idm', '').strip()

                # 脚質
                entry['run_style'] = row.get('txt_kyakusitsu', '').strip()

                results.append(entry)

            return results if results else None

        except Exception as e:
            print(f'  [JRDB] Error: {e}')
            return None

    def get_odds(self, race_date, rid):
        """JRDBからオッズ辞書を取得（即PATの代替）
        新コンテキストで開き直すため正確だが遅い（~20秒）

        Returns:
            dict: {馬番(int): 単勝オッズ(float)} or None
        """
        data = self.fetch_race(race_date, rid)
        if not data:
            return None
        odds = {}
        for entry in data:
            hn = entry.get('horse_number')
            tan = entry.get('tan_odds')
            if hn and tan and tan > 0:
                odds[hn] = tan
        return odds if odds else None

    def open_race_page(self, race_date, rid):
        """レースページを開いてオッズを取得可能にする（初回用）
        fetch_raceのリトライ付きロジックを使い、ページを開いたまま保持。
        以降はrefresh_odds()で高速にオッズを再取得できる。
        """
        data = self.fetch_race(race_date, rid)
        if data:
            # fetch_raceが成功 = ページが開いた状態でself.pageにある
            self._current_rid = rid
            # オッズ辞書も返す
            odds = {}
            for entry in data:
                hn = entry.get('horse_number')
                tan = entry.get('tan_odds')
                if hn and tan and tan > 0:
                    odds[hn] = tan
            return odds if odds else True
        return None

    def refresh_odds(self):
        """現在開いているページのオッズを再取得
        ページをリロードしてグリッドのオッズを読み直す
        """
        if not self.page:
            return None
        try:
            self.page.reload(timeout=30000, wait_until='networkidle')
            # SPA初期化 + jqGridデータ読み込みを待つ
            for _ in range(10):
                time.sleep(2)
                count = self.page.evaluate('''() => {
                    const grid = document.getElementById('horse_grid1');
                    if (!grid) return 0;
                    return grid.querySelectorAll('tr td[aria-describedby*="umaban"]').length;
                }''')
                if count > 0:
                    break

            raw_data = self.page.evaluate('''() => {
                const result = [];
                const grid = document.getElementById('horse_grid1');
                if (!grid) return result;
                const rows = grid.querySelectorAll('tr');
                for (const tr of rows) {
                    const cells = tr.querySelectorAll('td');
                    if (cells.length === 0) continue;
                    const row = {};
                    for (const td of cells) {
                        const desc = td.getAttribute('aria-describedby') || '';
                        const colName = desc.replace('horse_grid1_', '');
                        row[colName] = td.innerText.trim();
                    }
                    if (row['umaban']) result.push(row);
                }
                return result;
            }''')

            if not raw_data:
                return None

            odds = {}
            for row in raw_data:
                try:
                    hn = int(row.get('umaban', '0'))
                    tan = row.get('tanodds', '').strip()
                    if hn > 0 and tan:
                        odds[hn] = float(re.sub(r'[^\d.]', '', tan))
                except:
                    pass
            return odds if odds else None

        except Exception as e:
            return None

    def close(self):
        try:
            if self.browser:
                self.browser.close()
            if hasattr(self, 'pw'):
                self.pw.stop()
        except:
            pass


def save_to_db(rid, race_date, data):
    """パドックデータをDBに保存"""
    db = sqlite3.connect(DB_PATH)
    db.execute('''
        CREATE TABLE IF NOT EXISTS paddock_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id TEXT NOT NULL,
            race_date TEXT NOT NULL,
            horse_number INTEGER NOT NULL,
            horse_name TEXT,
            kehai_code INTEGER,
            kehai_text TEXT,
            batai_text TEXT,
            paddock_sirusi TEXT,
            weight INTEGER,
            weight_diff INTEGER,
            tan_odds REAL,
            fuku_odds REAL,
            idm_text TEXT,
            run_style TEXT,
            fetched_at TEXT NOT NULL,
            UNIQUE(race_id, horse_number)
        )
    ''')

    now = datetime.now().isoformat()
    count = 0
    for entry in data:
        try:
            db.execute('''
                INSERT OR REPLACE INTO paddock_info
                (race_id, race_date, horse_number, horse_name,
                 kehai_code, kehai_text, batai_text, paddock_sirusi,
                 weight, weight_diff, tan_odds, fuku_odds,
                 idm_text, run_style, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                rid, race_date, entry['horse_number'], entry.get('horse_name'),
                entry.get('kehai_code'), entry.get('kehai_text'),
                entry.get('batai_text'), entry.get('paddock_sirusi'),
                entry.get('weight'), entry.get('weight_diff'),
                entry.get('tan_odds'), entry.get('fuku_odds'),
                entry.get('idm_text'), entry.get('run_style'), now,
            ))
            count += 1
        except Exception as e:
            print(f'  [DB] Error: {e}')

    db.commit()
    db.close()
    return count


def print_paddock(data):
    """パドックデータを見やすく表示"""
    print(f'  {"馬番":>4} {"馬名":<16} {"体重":>4} {"増減":>5} {"気配":<8} {"単勝":>6} {"IDM":<8}')
    print(f'  {"─"*65}')
    for e in sorted(data, key=lambda x: x['horse_number']):
        hn = e['horse_number']
        name = e.get('horse_name', '')[:8]
        w = e.get('weight') or '-'
        wd = e.get('weight_diff', 0)
        wd_s = f'{wd:+d}' if isinstance(wd, int) and wd != 0 else '±0' if wd == 0 else str(wd)
        kehai = e.get('kehai_text', '-')
        odds = e.get('tan_odds')
        odds_s = f'{odds:.1f}' if odds else '-'
        idm = e.get('idm_text', '-')
        print(f'  {hn:>4} {name:<16} {str(w):>4} {wd_s:>5} {kehai:<8} {odds_s:>6} {idm:<8}')


def main():
    parser = argparse.ArgumentParser(description='JRDBパドック気配スクレイピング')
    parser.add_argument('--race', help='JRDB race_id (e.g. 26094401)')
    parser.add_argument('--today', action='store_true', help='本日の全レース')
    parser.add_argument('--test', action='store_true', help='テスト')
    parser.add_argument('--visible', action='store_true', help='ブラウザ表示')
    args = parser.parse_args()

    scraper = JRDBPaddockScraper(headless=not args.visible)
    scraper.start()

    try:
        if args.race or args.test:
            db = sqlite3.connect(DB_PATH)
            if args.race:
                rid = args.race
                row = db.execute(
                    'SELECT race_date, venue_name, race_number FROM races WHERE race_id=?', (rid,)
                ).fetchone()
            else:
                row_full = db.execute(
                    'SELECT race_id, race_date, venue_name, race_number '
                    'FROM races WHERE race_date=? ORDER BY start_time LIMIT 1',
                    (datetime.now().strftime('%Y-%m-%d'),)
                ).fetchone()
                if row_full:
                    rid = row_full[0]
                    row = row_full[1:]
                else:
                    row_full = db.execute(
                        'SELECT race_id, race_date, venue_name, race_number '
                        'FROM races ORDER BY race_date DESC LIMIT 1'
                    ).fetchone()
                    rid = row_full[0]
                    row = row_full[1:]
            db.close()

            if not row:
                print(f'Race {rid} not found')
                return

            rd, vn, rn = row
            print(f'=== {vn}{rn}R ({rd}) rid={rid} ===')

            data = scraper.fetch_race(rd, rid)
            if data:
                print(f'  取得成功: {len(data)}頭\n')
                print_paddock(data)
                n = save_to_db(rid, rd, data)
                print(f'\n  DB保存: {n}件')
            else:
                print('  取得失敗')

        elif args.today:
            today = datetime.now().strftime('%Y-%m-%d')
            db = sqlite3.connect(DB_PATH)
            races = db.execute(
                'SELECT race_id, venue_name, race_number, start_time '
                'FROM races WHERE race_date=? ORDER BY start_time',
                (today,)
            ).fetchall()
            db.close()

            print(f'=== {today} パドック気配取得 ({len(races)}R) ===')
            total = 0
            for rid, vn, rn, st in races:
                print(f'\n--- {vn}{rn}R ({st}) ---')
                data = scraper.fetch_race(today, rid)
                if data:
                    print_paddock(data)
                    n = save_to_db(rid, today, data)
                    total += n
                    print(f'  → {n}件保存')
                else:
                    print('  取得失敗')
                time.sleep(5)  # 429対策

            print(f'\n=== 完了: {total}件保存 ===')

        else:
            print('使い方:')
            print('  --race 26094401   指定レース')
            print('  --today           本日の全レース')
            print('  --test            テスト')
            print('  --visible         ブラウザ表示')

    finally:
        scraper.close()


if __name__ == '__main__':
    main()
