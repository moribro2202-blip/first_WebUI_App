# -*- coding: utf-8 -*-
"""入金テスト: ログイン → 残高確認 → 入金画面調査"""
import sys, time, re
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.abspath(__file__)))
from ipat_voter import IPATVoter

voter = IPATVoter(headless=False)
voter.login()
time.sleep(3)

# 残高確認
text = voter.page.evaluate('document.body.innerText')
for line in text.split('\n'):
    line = line.strip()
    if '購入限度額' in line or '残高' in line:
        print(f'  {line}')

# 入金ボタンをJSで呼び出し
print('\n=== 入金画面へ ===')
try:
    voter.page.evaluate('document.querySelector("[ng-click*=clickPayment]").click()')
    time.sleep(3)
    voter._screenshot('deposit_page')

    text2 = voter.page.evaluate('document.body.innerText')
    print('入金画面テキスト:')
    for line in text2.split('\n'):
        line = line.strip()
        if line and len(line) < 80:
            print(f'  {line}')

    # 入力欄
    html = voter.page.evaluate('document.body.innerHTML')
    inputs = voter.page.locator('input').all()
    print(f'\ninput要素:')
    for i, inp in enumerate(inputs):
        itype = inp.get_attribute('type') or ''
        iname = inp.get_attribute('name') or ''
        placeholder = inp.get_attribute('placeholder') or ''
        if itype not in ('hidden',):
            print(f'  [{i}] type={itype} name={iname} placeholder={placeholder}')

    # select要素
    selects = voter.page.locator('select').all()
    print(f'\nselect要素: {len(selects)}個')
    for i, sel in enumerate(selects):
        opts = sel.locator('option').all()
        labels = [(opt.get_attribute('label') or opt.text_content() or '').strip() for opt in opts]
        print(f'  [{i}] options: {labels[:10]}')

    # ボタン
    buttons = voter.page.locator('button').all()
    print(f'\nbutton要素:')
    for btn in buttons:
        txt = (btn.text_content() or '').strip()[:30]
        ng = btn.get_attribute('ng-click') or ''
        if txt:
            print(f'  "{txt}" ng-click={ng[:50]}')

except Exception as e:
    print(f'入金画面遷移エラー: {e}')

print('\n30秒後に終了...')
time.sleep(30)
voter.close()
print('Done!')
