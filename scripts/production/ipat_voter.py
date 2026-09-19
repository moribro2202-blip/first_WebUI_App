# -*- coding: utf-8 -*-
"""即PAT(IPAT)自動投票モジュール
Playwrightでブラウザ操作してJRA即PATに投票する。
即PATからオッズも取得可能。

前提:
  - 即PATの INET-ID、暗証番号、加入者番号、P-ARS番号が必要
  - 券種: 単勝のみ（τラグモデルの推奨設定）

使い方:
  1. .env に認証情報を設定
  2. realtime_runner.py から呼び出される
  3. 単体テスト: python ipat_voter.py --test
  4. オッズ取得テスト: python ipat_voter.py --odds 中山 1
"""
import os, sys, json, time, re
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')

def load_env():
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_path):
        print(f"  [ERROR] .env が見つかりません: {env_path}")
        return None
    config = {}
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                config[key.strip()] = val.strip()
    return config


class IPATVoter:
    """即PAT自動投票+オッズ取得クラス"""

    VENUE_NAMES = {
        '01': '札幌', '02': '函館', '03': '福島', '04': '新潟',
        '05': '東京', '06': '中山', '07': '中京', '08': '京都',
        '09': '阪神', '10': '小倉'
    }
    VENUE_CODES = {v: k for k, v in VENUE_NAMES.items()}

    def __init__(self, headless=False):
        self.config = load_env()
        if not self.config:
            raise ValueError(".env の設定が必要です")

        self.subscriber_id = self.config.get('IPAT_SUBSCRIBER_ID', '')  # INET-ID
        self.pin = self.config.get('IPAT_PIN', '')                      # 暗証番号
        self.pars = self.config.get('IPAT_PARS', '')                    # 加入者番号
        self.pars_number = self.config.get('IPAT_PARS_NUMBER', '7659')  # P-ARS番号
        self.bet_amount = int(self.config.get('BET_AMOUNT', '100'))
        self.max_bet_per_race = int(self.config.get('MAX_BET_PER_RACE', '1'))
        self.max_daily_loss = int(self.config.get('MAX_DAILY_LOSS', '10000'))

        self.headless = headless
        self.browser = None
        self.page = None
        self.logged_in = False
        self.daily_bet_total = 0
        self._base_url = None

        self.log_dir = os.path.join(BASE, 'data', 'ipat_log')
        os.makedirs(self.log_dir, exist_ok=True)

    def start_browser(self):
        from playwright.sync_api import sync_playwright
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=self.headless)
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        print(f"  [IPAT] ブラウザ起動 (headless={self.headless})")

    def login(self):
        """即PATにログイン"""
        if not self.page:
            self.start_browser()

        try:
            print(f"  [IPAT] ログイン中...")
            self.page.goto('https://www.ipat.jra.go.jp/', timeout=30000)
            time.sleep(2)

            # Step 1: INET-ID入力
            target = self.page
            for fr in self.page.frames:
                if fr.locator('input[name="inetid"]').all():
                    target = fr
                    break

            target.fill('input[name="inetid"]', self.subscriber_id)
            target.locator('input[name="inetid"]').press('Enter')
            time.sleep(3)

            # Step 2: 加入者番号 + 暗証番号 + P-ARS
            target2 = self.page
            for fr in self.page.frames:
                if fr.locator('input[name="p"]').all():
                    target2 = fr
                    break

            target2.fill('input[name="i"]', self.pars)          # 加入者番号
            target2.fill('input[name="p"]', self.pin)            # 暗証番号
            target2.fill('input[name="r"]', self.pars_number)    # P-ARS番号
            target2.locator('input[name="p"]').press('Enter')
            time.sleep(3)

            if 'エラー' in self.page.content():
                print(f"  [IPAT] ログイン失敗")
                self._screenshot('login_failed')
                self.logged_in = False
                return False

            self.logged_in = True
            self._base_url = self.page.url.split('#!/')[0]
            print(f"  [IPAT] ログイン成功")
            return True

        except Exception as e:
            print(f"  [IPAT] ログインエラー: {e}")
            self._screenshot('login_error')
            self.logged_in = False
            return False

    # ================================================================
    # SPA ナビゲーション
    # ================================================================

    def _go_to_odds_page(self):
        """オッズ投票（式別）ページに遷移し、ダイアログを閉じる"""
        self.page.goto(f'{self._base_url}#!/bet/odds/type', timeout=10000)
        time.sleep(3)
        try:
            self.page.click('text=このまま進む', timeout=3000)
            time.sleep(2)
        except:
            pass

    def _click_venue_button(self, venue_name, day=None):
        """場名ボタンをクリック（最初にマッチしたものを選択）
        day: '土' or '日' を指定すると曜日も絞り込む
        """
        day_filter = f" && t.includes('{day}')" if day else ""
        self.page.evaluate(f'''() => {{
            const buttons = document.querySelectorAll('button');
            for (const b of buttons) {{
                const t = b.innerText;
                const ng = b.getAttribute('ng-click') || '';
                if (t.includes('{venue_name}') && ng.includes('selectCourse'){day_filter}) {{
                    b.click();
                    break;
                }}
            }}
        }}''')
        time.sleep(2)

    def _click_race_button(self, race_number):
        """レース番号ボタンをクリック"""
        self.page.evaluate(f'''() => {{
            document.querySelectorAll('button').forEach(b => {{
                const t = b.innerText.trim();
                const ng = b.getAttribute('ng-click') || '';
                if (t.startsWith('{race_number}R') && ng.includes('selectRace')) b.click();
            }});
        }}''')
        time.sleep(2)

    # ================================================================
    # 開催情報取得
    # ================================================================

    def get_venues_and_races(self):
        """開催場・レース情報を取得

        Returns:
            list: [{'venue': '中山', 'day': '土', 'races': [1,...,12], 'race_info': [...]}, ...]
        """
        if not self.logged_in:
            if not self.login():
                return None

        try:
            print(f"  [IPAT] 開催情報取得中...")
            self._go_to_odds_page()

            # メインページのテキストからレース情報を取得
            text = self.page.evaluate('document.body.innerText')

            # 場名を取得（ボタンテキストから）
            venues_raw = self.page.evaluate('''() => {
                const result = [];
                document.querySelectorAll('button').forEach(b => {
                    const ng = b.getAttribute('ng-click') || '';
                    if (ng.includes('selectCourse')) {
                        result.push(b.innerText.trim().split('\\n')[0]);
                    }
                });
                return result;
            }''')

            result = []
            for vtext in venues_raw:
                # "中山（土）" → venue="中山", day="土"
                m = re.match(r'(.+?)[\(（](.+?)[\)）]', vtext)
                if not m:
                    continue
                venue = m.group(1)
                day = m.group(2)

                # この場名をクリックしてレース一覧を取得
                self._click_venue_button(venue)

                races = self.page.evaluate('''() => {
                    const result = [];
                    document.querySelectorAll('button').forEach(b => {
                        const ng = b.getAttribute('ng-click') || '';
                        const t = b.innerText.trim();
                        const m = t.match(/^(\\d+)R/);
                        if (m && ng.includes('selectRace')) {
                            result.push(parseInt(m[1]));
                        }
                    });
                    return result;
                }''')

                result.append({'venue': venue, 'day': day, 'races': sorted(races)})
                rstr = f"{races[0]}R〜{races[-1]}R" if races else "不明"
                print(f"    {venue}（{day}）: {len(races)}R ({rstr})")

            return result

        except Exception as e:
            print(f"  [IPAT] 開催情報取得エラー: {e}")
            self._screenshot('venues_error')
            return None

    # ================================================================
    # オッズ取得
    # ================================================================

    def get_odds(self, venue_name, race_number, day=None):
        """指定レースの単勝オッズを取得

        Returns:
            dict: {馬番(int): 単勝オッズ(float)} or None
        """
        if not self.logged_in:
            if not self.login():
                return None

        try:
            self._go_to_odds_page()
            self._click_venue_button(venue_name, day=day)
            self._click_race_button(race_number)

            odds = self._parse_odds_from_dom()
            if odds:
                print(f"  [IPAT] オッズ取得成功: {venue_name}{race_number}R {len(odds)}頭")
            else:
                print(f"  [IPAT] オッズ取得失敗: {venue_name}{race_number}R")
                self._screenshot(f'odds_fail_{venue_name}_{race_number}R')
            return odds

        except Exception as e:
            print(f"  [IPAT] オッズ取得エラー: {e}")
            self._screenshot('odds_error')
            return None

    def get_all_odds(self, venue_name, day=None):
        """指定会場の全レースのオッズを一括取得

        Returns:
            dict: {race_number(int): {馬番: 単勝オッズ}}
        """
        if not self.logged_in:
            if not self.login():
                return None

        try:
            print(f"  [IPAT] {venue_name}{'（'+day+'）' if day else ''} 全レースオッズ取得中...")
            self._go_to_odds_page()
            self._click_venue_button(venue_name, day=day)

            all_odds = {}
            for race_num in range(1, 13):
                self._click_race_button(race_num)
                odds = self._parse_odds_from_dom()
                if odds:
                    all_odds[race_num] = odds
                    fav = min(odds.values())
                    print(f"    {race_num}R: {len(odds)}頭 (1番人気={fav:.1f}倍)")

            print(f"  [IPAT] 取得完了: {len(all_odds)}レース")
            return all_odds

        except Exception as e:
            print(f"  [IPAT] 全オッズ取得エラー: {e}")
            return None

    def refresh_odds_on_page(self, race_number):
        """現在表示中のページでオッズを再取得（レースボタン再クリックのみ、軽量）
        get_odds() の ~7秒に対して ~2.5秒で完了する。
        """
        try:
            self._click_race_button(race_number)
            return self._parse_odds_from_dom()
        except Exception as e:
            print(f"  [IPAT] オッズ再取得エラー: {e}")
            return None

    def _parse_odds_from_dom(self):
        """DOMから単勝オッズテーブルをパース

        Returns:
            dict: {馬番(int): オッズ(float)} or None
        """
        data = self.page.evaluate('''() => {
            const result = [];
            const rows = document.querySelectorAll('table.winplace-table tbody tr');
            for (const row of rows) {
                const noEl = row.querySelector('.ipat-racer-no');
                const oddsEl = row.querySelector('.odds-win .odds-num');
                if (noEl && oddsEl) {
                    const hn = parseInt(noEl.innerText.trim());
                    const odds = parseFloat(oddsEl.innerText.trim());
                    if (hn > 0 && odds > 0) result.push({hn, odds});
                }
            }
            return result;
        }''')

        if not data:
            return None
        return {d['hn']: d['odds'] for d in data}

    # ================================================================
    # 投票
    # ================================================================

    def place_bet(self, venue_code, race_number, horse_number, amount=None,
                  bet_type='win', ev=0, model_prob=0, odds_1min=0):
        """単勝投票実行（オッズ投票画面から）"""
        if amount is None:
            amount = self.bet_amount

        if self.daily_bet_total + amount > self.max_daily_loss:
            print(f"  [IPAT] 日次上限超過: {self.daily_bet_total}+{amount} > {self.max_daily_loss}")
            self._log_bet(venue_code, race_number, horse_number, amount, 'daily_limit', ev, model_prob, odds_1min)
            return False, "daily_limit_exceeded"

        if not self.logged_in:
            if not self.login():
                return False, "login_failed"

        venue_name = self.VENUE_NAMES.get(venue_code, '')

        try:
            print(f"  [IPAT] 投票: {venue_name}{race_number}R 馬番{horse_number} 単勝 {amount}円 (EV={ev:.3f})")

            # オッズ投票画面に遷移
            self._go_to_odds_page()
            self._click_venue_button(venue_name)
            self._click_race_button(race_number)

            self._screenshot(f'bet_before_{race_number}R')

            # 該当馬番の単勝オッズボタンをクリック（スクロールしてから）
            clicked = self.page.evaluate(f'''() => {{
                const rows = document.querySelectorAll('table.winplace-table tbody tr');
                for (const row of rows) {{
                    const noEl = row.querySelector('.ipat-racer-no');
                    if (noEl && parseInt(noEl.innerText.trim()) === {horse_number}) {{
                        row.scrollIntoView({{block: 'center'}});
                        const btn = row.querySelector('.odds-win .btn-odds');
                        if (btn) {{ btn.scrollIntoView({{block: 'center'}}); btn.click(); return true; }}
                    }}
                }}
                return false;
            }}''')

            if not clicked:
                # リトライ: 少し待ってからもう一度
                time.sleep(1)
                clicked = self.page.evaluate(f'''() => {{
                    const rows = document.querySelectorAll('table.winplace-table tbody tr');
                    for (const row of rows) {{
                        const noEl = row.querySelector('.ipat-racer-no');
                        if (noEl && parseInt(noEl.innerText.trim()) === {horse_number}) {{
                            row.scrollIntoView({{block: 'center'}});
                            const btn = row.querySelector('.odds-win .btn-odds');
                            if (btn) {{ btn.click(); return true; }}
                        }}
                    }}
                    return false;
                }}''')

            if not clicked:
                print(f"  [IPAT] 馬番{horse_number}の選択失敗（スクロール後も）")
                self._log_bet(venue_code, race_number, horse_number, amount, 'select_failed', ev, model_prob, odds_1min)
                return False, "select_failed"

            time.sleep(1)

            # 金額入力（100円単位）
            amount_100 = amount // 100
            unit_input = self.page.locator('input[ng-model="vm.nUnit"]').first
            unit_input.fill(str(amount_100))
            time.sleep(0.5)

            # セット
            self.page.evaluate('''() => {
                document.querySelectorAll('button').forEach(b => {
                    if (b.innerText.trim() === 'セット') b.click();
                });
            }''')
            time.sleep(1)

            self._screenshot(f'bet_set_{race_number}R')

            # 購入する
            self.page.evaluate("document.querySelectorAll('button').forEach(b => { if(b.innerText.includes('購入する')) b.click(); })")
            time.sleep(2)

            # 確認ダイアログ（OK / はい）
            for confirm_text in ['OK', 'はい', '購入']:
                try:
                    self.page.click(f'text={confirm_text}', timeout=2000)
                    time.sleep(1)
                except:
                    pass

            self._screenshot(f'bet_result_{race_number}R')

            # 結果確認
            text = self.page.evaluate('document.body.innerText')
            if '受付' in text or '完了' in text:
                status = 'success'
                self.daily_bet_total += amount
                print(f"  [IPAT] 投票成功: {venue_name}{race_number}R {horse_number}番 {amount}円")
            else:
                status = 'uncertain'
                print(f"  [IPAT] 投票結果不明（手動確認が必要）")

        except Exception as e:
            status = 'error'
            print(f"  [IPAT] 投票エラー: {e}")
            self._screenshot(f'bet_error_{race_number}R')

        self._log_bet(venue_code, race_number, horse_number, amount, status, ev, model_prob, odds_1min)
        return status == 'success', status

    def place_multi_bets_batch(self, venue_name, race_number, bets_list):
        """三連複・三連単を一括投票（同一レース、まとめてセット→1回で購入）

        Args:
            venue_name: '中山', '阪神' etc.
            race_number: レース番号
            bets_list: [{'bet_type': 'sanrenpuku'|'sanrentan', 'combination': (h1,h2,h3), 'amount': 100, 'ev': 1.0}, ...]

        Returns:
            (success_count, total_count)
        """
        if not bets_list:
            return 0, 0
        if not self.logged_in:
            if not self.login():
                return 0, 0

        total = len(bets_list)
        try:
            # 1. オッズ投票画面→場所→レース選択
            self._go_to_odds_page()
            self._click_venue_button(venue_name)
            self._click_race_button(race_number)
            time.sleep(2)

            set_count = 0
            current_type = None
            current_axis = None

            # 同じ券種・同じ1着馬をまとめるためにソート
            # 三連単(string:8)を先、三連複(string:7)を後にする
            # 三連単は1着馬(h1)でグループ化
            sorted_bets = sorted(bets_list, key=lambda b: (
                0 if b['bet_type'] == 'sanrentan' else 1,
                b['combination'][0] if b['bet_type'] == 'sanrentan' else 0
            ))

            for bet in sorted_bets:
                bt = bet['bet_type']
                h1, h2, h3 = bet['combination']
                amount = bet.get('amount', 100)
                combo_str = f'{h1}-{h2}-{h3}'

                # 式別が変わったら切り替え
                type_id = 'string:7' if bt == 'sanrenpuku' else 'string:8'
                if current_type != type_id:
                    self.page.evaluate(f'''() => {{
                        var sel = document.querySelector('select[ng-model="vm.cSelectTypeId"]');
                        if (!sel) return;
                        for (var i=0; i<sel.options.length; i++) {{
                            if (sel.options[i].value === '{type_id}') {{
                                sel.selectedIndex = i;
                                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                                var e = document.createEvent('HTMLEvents');
                                e.initEvent('change', true, true);
                                sel.dispatchEvent(e);
                                return;
                            }}
                        }}
                    }}''')
                    time.sleep(4)  # 式別切替後のオッズ読込に時間がかかる
                    current_type = type_id
                    current_axis = None

                # 軸馬が変わったら切替（三連単=1着馬、三連複=最小馬番）
                axis_horse = h1 if bt == 'sanrentan' else min(h1, h2, h3)
                if axis_horse != current_axis:
                    self.page.evaluate(f'''() => {{
                        var sel = document.querySelector('select[ng-model="vm.oSelectAxisHorse"]');
                        if (!sel) return;
                        for (var i=0; i<sel.options.length; i++) {{
                            if (parseInt(sel.options[i].text) === {axis_horse}) {{
                                sel.selectedIndex = i;
                                sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                                var e = document.createEvent('HTMLEvents');
                                e.initEvent('change', true, true);
                                sel.dispatchEvent(e);
                                return;
                            }}
                        }}
                    }}''')
                    time.sleep(2)
                    current_axis = axis_horse

                # オッズボタンをクリック
                if bt == 'sanrenpuku':
                    sh1, sh2, sh3 = sorted([h1, h2, h3])
                    clicked = self.page.evaluate(f'''() => {{
                        var btns = document.querySelectorAll('.btn-odds');
                        for (var i=0; i<btns.length; i++) {{
                            var scope = angular.element(btns[i]).scope();
                            var o = (scope && scope.oOdds) ? scope.oOdds : (scope && scope.odds) ? scope.odds : null;
                            if (o && parseInt(o.horse1)==={sh1} && parseInt(o.horse2)==={sh2} && parseInt(o.horse3)==={sh3}) {{
                                btns[i].scrollIntoView({{block: 'center'}});
                                btns[i].click();
                                return true;
                            }}
                        }}
                        return false;
                    }}''')
                else:
                    clicked = self.page.evaluate(f'''() => {{
                        var btns = document.querySelectorAll('.btn-odds');
                        for (var i=0; i<btns.length; i++) {{
                            var scope = angular.element(btns[i]).scope();
                            var o = (scope && scope.odds) ? scope.odds : (scope && scope.oOdds) ? scope.oOdds : null;
                            if (o && parseInt(o.horse1)==={h1} && parseInt(o.horse2)==={h2} && parseInt(o.horse3)==={h3}) {{
                                btns[i].scrollIntoView({{block: 'center'}});
                                btns[i].click();
                                return true;
                            }}
                        }}
                        return false;
                    }}''')

                if not clicked:
                    print(f"  [IPAT] {combo_str} 見つからず、スキップ")
                    continue

                time.sleep(0.5)

                # 金額入力 + セット
                amount_100 = amount // 100
                unit_input = self.page.locator('input[ng-model="vm.nUnit"]').first
                unit_input.click()
                unit_input.fill(str(amount_100))
                time.sleep(0.3)

                self.page.evaluate('''() => {
                    var btns = document.querySelectorAll('button[ng-click="vm.onSet()"]');
                    for (var i=0; i<btns.length; i++) {
                        if (btns[i].offsetParent !== null) { btns[i].click(); return; }
                    }
                }''')
                time.sleep(0.5)
                set_count += 1
                type_jp = '三連複' if bt == 'sanrenpuku' else '三連単'
                print(f"  [IPAT] セット {set_count}/{total}: {type_jp} {combo_str} {amount}円")

            if set_count == 0:
                print(f"  [IPAT] セットできた点数が0")
                return 0, total

            # 入力終了
            self.page.evaluate('''() => {
                var btns = document.querySelectorAll('button[ng-click="vm.onShowBetList()"]');
                for (var i=0; i<btns.length; i++) {
                    if (btns[i].offsetParent !== null) { btns[i].click(); return; }
                }
            }''')
            time.sleep(2)

            # 合計金額入力
            total_amount = sum(b.get('amount', 100) for b in bets_list[:set_count])
            self.page.evaluate(f'''() => {{
                var inp = document.querySelector('input[ng-model="vm.cAmountTotal"]');
                if (inp && inp.offsetParent !== null) {{
                    inp.focus();
                    inp.value = '{total_amount}';
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}''')
            time.sleep(1)

            # 購入する
            self.page.evaluate('''() => {
                var btns = document.querySelectorAll('button[ng-click="vm.clickPurchase()"]');
                for (var i=0; i<btns.length; i++) {
                    if (btns[i].offsetParent !== null) { btns[i].click(); return; }
                }
            }''')
            time.sleep(3)

            # PARS暗証番号
            pars = self.config.get('IPAT_PARS_NUMBER', '')
            if pars:
                try:
                    pars_input = self.page.locator('input[type="password"]')
                    if pars_input.count() > 0:
                        pars_input.first.fill(pars)
                        time.sleep(0.5)
                        self.page.evaluate('''() => {
                            var btns = document.querySelectorAll('button');
                            for (var i=0; i<btns.length; i++) {
                                var text = btns[i].innerText.trim();
                                if (btns[i].offsetParent !== null && (text === '購入' || text === 'OK' || text === '投票する')) {
                                    btns[i].click(); return;
                                }
                            }
                        }''')
                        time.sleep(2)
                except:
                    pass

            # 確認ダイアログ
            for ct in ['OK', 'はい']:
                try:
                    self.page.click(f'text={ct}', timeout=2000)
                    time.sleep(1)
                except:
                    pass

            # 結果確認
            text = self.page.evaluate('document.body.innerText')
            if '受付' in text or '完了' in text:
                self.daily_bet_total += total_amount
                print(f"  [IPAT] 一括投票成功: {set_count}点 {total_amount}円")
                return set_count, total
            else:
                print(f"  [IPAT] 一括投票結果不明")
                return 0, total

        except Exception as e:
            print(f"  [IPAT] 一括投票エラー: {e}")
            return 0, total

    def place_multi_bet(self, venue_name, race_number, bet_type, combination, amount=100,
                         ev=0, model_prob=0):
        """三連複・三連単の投票（オッズ投票画面から）

        Args:
            venue_name: '中山', '阪神' etc.
            race_number: レース番号
            bet_type: 'sanrenpuku' or 'sanrentan'
            combination: (h1, h2, h3) のタプル。三連複はソート済み、三連単は着順
            amount: 金額（100円単位）
            ev: EV値（ログ用）
            model_prob: モデル確率（ログ用）
        """
        if amount < 100:
            amount = 100
        if self.daily_bet_total + amount > self.max_daily_loss:
            print(f"  [IPAT] 日次上限超過")
            return False, "daily_limit_exceeded"
        if not self.logged_in:
            if not self.login():
                return False, "login_failed"

        h1, h2, h3 = combination
        type_id = 'string:7' if bet_type == 'sanrenpuku' else 'string:8'
        type_jp = '三連複' if bet_type == 'sanrenpuku' else '三連単'
        combo_str = f'{h1}-{h2}-{h3}'

        try:
            print(f"  [IPAT] 投票: {venue_name}{race_number}R {type_jp} {combo_str} {amount}円 (EV={ev:.3f})")

            # 1. オッズ投票画面→場所→レース選択
            self._go_to_odds_page()
            self._click_venue_button(venue_name)
            self._click_race_button(race_number)
            time.sleep(2)

            # 2. 式別をSELECTで切り替え
            self.page.evaluate(f'''() => {{
                var sel = document.querySelector('select[ng-model="vm.cSelectTypeId"]');
                if (!sel) return false;
                for (var i=0; i<sel.options.length; i++) {{
                    if (sel.options[i].value === '{type_id}') {{
                        sel.selectedIndex = i;
                        sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                        var e = document.createEvent('HTMLEvents');
                        e.initEvent('change', true, true);
                        sel.dispatchEvent(e);
                        return true;
                    }}
                }}
                return false;
            }}''')
            time.sleep(3)

            # 3. 該当組合せのbtn-oddsをAngularJSスコープから探してクリック
            # 三連複: scope.oOdds, 三連単: scope.odds (変数名が異なる)
            if bet_type == 'sanrenpuku':
                # 三連複: h1<=h2<=h3 でソート済み
                sh1, sh2, sh3 = sorted([h1, h2, h3])
                clicked = self.page.evaluate(f'''() => {{
                    var btns = document.querySelectorAll('.btn-odds');
                    for (var i=0; i<btns.length; i++) {{
                        var scope = angular.element(btns[i]).scope();
                        var o = (scope && scope.oOdds) ? scope.oOdds : (scope && scope.odds) ? scope.odds : null;
                        if (o && parseInt(o.horse1)==={sh1} && parseInt(o.horse2)==={sh2} && parseInt(o.horse3)==={sh3}) {{
                            btns[i].scrollIntoView({{block: 'center'}});
                            btns[i].click();
                            return true;
                        }}
                    }}
                    return false;
                }}''')
            else:
                # 三連単: まず1着馬をvm.oSelectAxisHorseで選択
                self.page.evaluate(f'''() => {{
                    var sel = document.querySelector('select[ng-model="vm.oSelectAxisHorse"]');
                    if (!sel) return false;
                    for (var i=0; i<sel.options.length; i++) {{
                        var text = sel.options[i].text;
                        var num = parseInt(text);
                        if (num === {h1}) {{
                            sel.selectedIndex = i;
                            sel.dispatchEvent(new Event('change', {{bubbles: true}}));
                            var e = document.createEvent('HTMLEvents');
                            e.initEvent('change', true, true);
                            sel.dispatchEvent(e);
                            return true;
                        }}
                    }}
                    return false;
                }}''')
                time.sleep(3)

                # h1=1着が選択済み → h2=2着, h3=3着のbtn-oddsをクリック
                clicked = self.page.evaluate(f'''() => {{
                    var btns = document.querySelectorAll('.btn-odds');
                    for (var i=0; i<btns.length; i++) {{
                        var scope = angular.element(btns[i]).scope();
                        var o = (scope && scope.odds) ? scope.odds : (scope && scope.oOdds) ? scope.oOdds : null;
                        if (o && parseInt(o.horse1)==={h1} && parseInt(o.horse2)==={h2} && parseInt(o.horse3)==={h3}) {{
                            btns[i].scrollIntoView({{block: 'center'}});
                            btns[i].click();
                            return true;
                        }}
                    }}
                    return false;
                }}''')

            if not clicked:
                print(f"  [IPAT] 組合せ {combo_str} が見つかりません")
                self._screenshot(f'multi_notfound_{race_number}R_{combo_str}')
                return False, "combo_not_found"

            time.sleep(1)

            # 4. 金額入力（vm.nUnit）
            amount_100 = amount // 100
            unit_input = self.page.locator('input[ng-model="vm.nUnit"]').first
            unit_input.click()
            unit_input.fill(str(amount_100))
            time.sleep(0.5)

            # 5. セット（vm.onSet()）
            self.page.evaluate('''() => {
                var btns = document.querySelectorAll('button[ng-click="vm.onSet()"]');
                for (var i=0; i<btns.length; i++) {
                    if (btns[i].offsetParent !== null) { btns[i].click(); return; }
                }
            }''')
            time.sleep(1)

            self._screenshot(f'multi_set_{race_number}R_{combo_str}')

            # 6. 入力終了（vm.onShowBetList()）→ 購入予定リスト表示
            self.page.evaluate('''() => {
                var btns = document.querySelectorAll('button[ng-click="vm.onShowBetList()"]');
                for (var i=0; i<btns.length; i++) {
                    if (btns[i].offsetParent !== null) { btns[i].click(); return; }
                }
            }''')
            time.sleep(2)

            # 7. 合計金額入力（vm.cAmountTotal） — 購入確認用
            total_amount = amount  # 1点の場合。複数点まとめ買い時は呼び出し側で調整
            self.page.evaluate(f'''() => {{
                var inp = document.querySelector('input[ng-model="vm.cAmountTotal"]');
                if (inp && inp.offsetParent !== null) {{
                    inp.focus();
                    inp.value = '{total_amount}';
                    inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                    inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                }}
            }}''')
            time.sleep(1)

            # 8. 購入する（vm.clickPurchase()）
            self.page.evaluate('''() => {
                var btns = document.querySelectorAll('button[ng-click="vm.clickPurchase()"]');
                for (var i=0; i<btns.length; i++) {
                    if (btns[i].offsetParent !== null) { btns[i].click(); return; }
                }
            }''')
            time.sleep(3)

            # 9. INET-ID暗証番号入力（PARS番号）が求められる場合
            pars = self.config.get('IPAT_PARS_NUMBER', '')
            if pars:
                try:
                    pars_input = self.page.locator('input[type="password"]')
                    if pars_input.count() > 0:
                        pars_input.first.fill(pars)
                        time.sleep(0.5)
                        # 購入確定ボタン
                        self.page.evaluate('''() => {
                            var btns = document.querySelectorAll('button');
                            for (var i=0; i<btns.length; i++) {
                                var text = btns[i].innerText.trim();
                                if (btns[i].offsetParent !== null && (text === '購入' || text === 'OK' || text === '投票する')) {
                                    btns[i].click(); return;
                                }
                            }
                        }''')
                        time.sleep(2)
                except:
                    pass

            # 10. 確認ダイアログ（追加のOK/はい）
            for confirm_text in ['OK', 'はい']:
                try:
                    self.page.click(f'text={confirm_text}', timeout=2000)
                    time.sleep(1)
                except:
                    pass

            self._screenshot(f'multi_result_{race_number}R_{combo_str}')

            # 10. 結果確認
            text = self.page.evaluate('document.body.innerText')
            if '受付' in text or '完了' in text:
                self.daily_bet_total += amount
                print(f"  [IPAT] 投票成功: {type_jp} {combo_str} {amount}円")
                status = 'success'
            elif '購入予定リスト' in text:
                print(f"  [IPAT] 購入確認画面で停止（手動確認要）")
                status = 'uncertain'
            else:
                print(f"  [IPAT] 投票結果不明（手動確認要）")
                status = 'uncertain'

        except Exception as e:
            status = 'error'
            print(f"  [IPAT] 投票エラー: {e}")
            self._screenshot(f'multi_error_{race_number}R_{combo_str}')

        self._log_bet_multi(venue_name, race_number, bet_type, combo_str, amount, status, ev, model_prob)
        return status == 'success', status

    def _log_bet_multi(self, venue_name, race_number, bet_type, combo_str, amount, status, ev, model_prob):
        record = {
            'timestamp': datetime.now().isoformat(),
            'venue_name': venue_name,
            'race_number': race_number,
            'bet_type': bet_type,
            'combination': combo_str,
            'amount': amount,
            'status': status,
            'ev': ev,
            'model_prob': model_prob,
            'daily_total': self.daily_bet_total,
        }
        log_path = os.path.join(self.log_dir, f'bet_{datetime.now().strftime("%Y%m%d")}.jsonl')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

    def navigate_to_bet_screen(self, venue_name, race_number, horse_number):
        """投票画面まで遷移して該当馬番を選択状態にする（投票はしない）"""
        if not self.logged_in:
            if not self.login():
                return False

        self._go_to_odds_page()
        self._click_venue_button(venue_name)
        self._click_race_button(race_number)

        # 該当馬番の単勝オッズボタンをクリック（選択状態にする）
        self.page.evaluate(f'''() => {{
            const rows = document.querySelectorAll('table.winplace-table tbody tr');
            for (const row of rows) {{
                const noEl = row.querySelector('.ipat-racer-no');
                if (noEl && parseInt(noEl.innerText.trim()) === {horse_number}) {{
                    const btn = row.querySelector('.odds-win .btn-odds');
                    if (btn) btn.click();
                }}
            }}
        }}''')
        time.sleep(1)

        self._screenshot(f'ready_{venue_name}_{race_number}R_{horse_number}')
        return True

    # ================================================================
    # ユーティリティ
    # ================================================================

    def _screenshot(self, name):
        try:
            ss_path = os.path.join(self.log_dir, f'ss_{datetime.now().strftime("%Y%m%d_%H%M%S")}_{name}.png')
            self.page.screenshot(path=ss_path)
        except:
            pass

    def _log_bet(self, venue_code, race_number, horse_number, amount, status, ev, model_prob, odds_1min):
        record = {
            'timestamp': datetime.now().isoformat(),
            'venue_code': venue_code,
            'race_number': race_number,
            'horse_number': horse_number,
            'bet_type': 'win',
            'amount': amount,
            'status': status,
            'ev': ev,
            'model_prob': model_prob,
            'odds_1min': odds_1min,
            'daily_total': self.daily_bet_total,
        }
        log_path = os.path.join(self.log_dir, f'bet_{datetime.now().strftime("%Y%m%d")}.jsonl')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

    def close(self):
        try:
            if self.browser:
                self.browser.close()
            if hasattr(self, 'pw'):
                self.pw.stop()
        except:
            pass
        print(f"  [IPAT] ブラウザ終了 (本日投票額: {self.daily_bet_total}円)")


class PaperTrader:
    """ペーパートレード（実投票なし、記録のみ）"""

    def __init__(self):
        self.log_dir = os.path.join(BASE, 'data', 'paper_trade_log')
        os.makedirs(self.log_dir, exist_ok=True)
        self.daily_bets = []
        self.bet_amount = 100
        self.max_bet_per_race = 1

    def place_bet(self, venue_code, race_number, horse_number, amount=100, bet_type='win',
                  ev=0, model_prob=0, odds_1min=0):
        record = {
            'timestamp': datetime.now().isoformat(),
            'venue_code': venue_code,
            'race_number': race_number,
            'horse_number': horse_number,
            'bet_type': 'win',
            'amount': amount,
            'ev': ev,
            'model_prob': model_prob,
            'odds_1min': odds_1min,
            'status': 'paper'
        }
        self.daily_bets.append(record)
        print(f"  [PAPER] {race_number}R {horse_number}番 EV={ev:.3f} odds={odds_1min:.1f} {amount}円")

        log_path = os.path.join(self.log_dir, f'paper_{datetime.now().strftime("%Y%m%d")}.jsonl')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')

        return True, 'paper'

    def close(self):
        pass


# === CLI ===
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true', help='ログインテスト')
    parser.add_argument('--venues', action='store_true', help='開催場・レース情報取得')
    parser.add_argument('--odds', nargs=2, metavar=('VENUE', 'RACE'), help='オッズ取得テスト (例: --odds 中山 1)')
    parser.add_argument('--all-odds', metavar='VENUE', help='全レースオッズ取得 (例: --all-odds 中山)')
    parser.add_argument('--paper', action='store_true', help='ペーパートレードテスト')
    args = parser.parse_args()

    if args.venues:
        print("=== 開催場・レース情報 ===")
        voter = IPATVoter(headless=False)
        voter.login()
        info = voter.get_venues_and_races()
        time.sleep(5)
        voter.close()

    elif args.all_odds:
        print(f"=== {args.all_odds} 全レースオッズ ===")
        voter = IPATVoter(headless=False)
        voter.login()
        all_odds = voter.get_all_odds(args.all_odds)
        if all_odds:
            for rnum in sorted(all_odds.keys()):
                odds = all_odds[rnum]
                for hn in sorted(odds.keys()):
                    print(f"    {rnum}R 馬番{hn:>2}: {odds[hn]:>6.1f}倍")
        time.sleep(5)
        voter.close()

    elif args.odds:
        venue_name, race_num = args.odds[0], int(args.odds[1])
        print(f"=== オッズ取得テスト: {venue_name} {race_num}R ===")
        voter = IPATVoter(headless=False)
        voter.login()
        odds = voter.get_odds(venue_name, race_num)
        if odds:
            print(f"\n  取得成功: {len(odds)}頭")
            for hn in sorted(odds.keys()):
                print(f"    馬番{hn:>2}: {odds[hn]:>6.1f}倍")
        else:
            print(f"\n  取得失敗")
        time.sleep(5)
        voter.close()

    elif args.test:
        print("=== 即PATログインテスト ===")
        config = load_env()
        if not config:
            sys.exit(1)
        print(f"  INET-ID: {config.get('IPAT_SUBSCRIBER_ID', 'NOT SET')[:4]}****")
        print(f"  ベット金額: {config.get('BET_AMOUNT', 'NOT SET')}円")
        print(f"  日次上限: {config.get('MAX_DAILY_LOSS', 'NOT SET')}円")
        voter = IPATVoter(headless=False)
        success = voter.login()
        if success:
            print("  ログイン成功！")
        time.sleep(5)
        voter.close()

    elif args.paper:
        print("=== ペーパートレードテスト ===")
        trader = PaperTrader()
        trader.place_bet('06', 1, 3, 100, 'win', ev=1.15, model_prob=0.08, odds_1min=14.5)
        trader.close()

    else:
        print("使い方:")
        print("  python ipat_voter.py --test              # ログインテスト")
        print("  python ipat_voter.py --venues            # 開催場情報")
        print("  python ipat_voter.py --odds 中山 1       # オッズ取得テスト")
        print("  python ipat_voter.py --all-odds 中山     # 全レースオッズ")
        print("  python ipat_voter.py --paper             # ペーパートレードテスト")
