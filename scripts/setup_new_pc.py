# -*- coding: utf-8 -*-
"""別PCセットアップスクリプト
このスクリプトを新しいPCで実行して環境を構築する。

前提:
  - Windows 11
  - Python 3.12 (64bit) がインストール済み
  - Node.js 20.x がインストール済み
  - Git がインストール済み

使い方:
  1. リポジトリをクローン: git clone <repo-url>
  2. このスクリプトを実行: python scripts/setup_new_pc.py
  3. 指示に従って .env と data/ を配置
"""
import os, sys, subprocess, shutil

def run(cmd, desc=None, check=True):
    if desc:
        print(f"\n{'='*60}")
        print(f"  {desc}")
        print(f"{'='*60}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout[:500])
    if result.returncode != 0 and check:
        print(f"  [ERROR] {result.stderr[:300]}")
        return False
    return True

def check_command(cmd, name):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        return result.returncode == 0
    except:
        return False

def main():
    print()
    print("=" * 60)
    print("  競馬AI セットアップスクリプト")
    print("=" * 60)
    print()

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    os.chdir(base)
    print(f"  作業ディレクトリ: {base}")

    # === Step 1: 前提条件チェック ===
    print("\n\n[Step 1/6] 前提条件チェック")
    print("-" * 40)

    checks = {
        "Python": ("python --version", "python"),
        "Node.js": ("node --version", "node"),
        "npm": ("npm --version", "npm"),
        "Git": ("git --version", "git"),
    }
    all_ok = True
    for name, (cmd, _) in checks.items():
        ok = check_command(cmd, name)
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        ver = result.stdout.strip() if ok else "NOT FOUND"
        status = "OK" if ok else "NG"
        print(f"  {name:>10}: {ver} [{status}]")
        if not ok:
            all_ok = False

    if not all_ok:
        print("\n  [ERROR] 不足しているツールをインストールしてください。")
        print("  Python: https://www.python.org/downloads/")
        print("  Node.js: https://nodejs.org/")
        sys.exit(1)

    # === Step 2: Node依存インストール ===
    print("\n\n[Step 2/6] Node.js 依存パッケージ")
    print("-" * 40)

    if os.path.exists("node_modules"):
        print("  node_modules/ 既存 → スキップ")
    else:
        run("npm install", "npm install 実行中...")

    # === Step 3: Python依存インストール ===
    print("\n\n[Step 3/6] Python 依存パッケージ")
    print("-" * 40)

    pip_packages = [
        "lightgbm>=4.0",
        "scipy",
        "numpy",
        "playwright",
    ]

    for pkg in pip_packages:
        pkg_name = pkg.split(">=")[0].split("==")[0]
        try:
            __import__(pkg_name)
            print(f"  {pkg_name}: OK (既にインストール済み)")
        except ImportError:
            print(f"  {pkg_name}: インストール中...")
            run(f"pip install {pkg}", check=False)

    # Playwrightブラウザ
    print("  Playwright ブラウザ確認中...")
    run("python -m playwright install chromium", check=False)

    # === Step 4: ディレクトリ構造 ===
    print("\n\n[Step 4/6] ディレクトリ構造")
    print("-" * 40)

    dirs = ["data", "data/models", "data/jrdb", "data/realtime_log"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"  {d}/ OK")

    # === Step 5: 必要ファイルのチェック ===
    print("\n\n[Step 5/6] 必要ファイルのチェック")
    print("-" * 40)

    required_files = {
        "data/jrdb.db": {
            "desc": "JRDBデータベース (18GB)",
            "how": "元PCから data/jrdb.db をコピー（USB or ネットワーク共有）",
            "critical": True,
        },
        "data/models/prod_config.json": {
            "desc": "本番モデル設定",
            "how": "元PCから data/models/ フォルダごとコピー",
            "critical": True,
        },
        "data/models/prod_model_v16.txt": {
            "desc": "本番LightGBMモデル",
            "how": "data/models/ に含まれる",
            "critical": True,
        },
        "data/models/prod_stats_v16.json": {
            "desc": "騎手・馬・調教師の累積統計",
            "how": "data/models/ に含まれる",
            "critical": True,
        },
        "scripts/production/.env": {
            "desc": "認証情報（JRDB/即PAT）",
            "how": "scripts/production/.env.example をコピーして編集",
            "critical": True,
        },
    }

    missing = []
    for fpath, info in required_files.items():
        exists = os.path.exists(fpath)
        status = "OK" if exists else "MISSING"
        mark = "  " if exists else ">>"
        print(f"  {mark} {fpath}: [{status}] {info['desc']}")
        if not exists:
            missing.append((fpath, info))

    if missing:
        print(f"\n  {'='*50}")
        print(f"  {len(missing)}個のファイルが不足しています:")
        print(f"  {'='*50}")
        for fpath, info in missing:
            print(f"\n  >> {fpath}")
            print(f"     {info['desc']}")
            print(f"     取得方法: {info['how']}")

        # .envが不足 → テンプレートからコピー
        env_path = "scripts/production/.env"
        env_example = "scripts/production/.env.example"
        if not os.path.exists(env_path) and os.path.exists(env_example):
            shutil.copy2(env_example, env_path)
            print(f"\n  .env.example → .env にコピーしました。認証情報を編集してください。")

    # === Step 6: 動作テスト ===
    print("\n\n[Step 6/6] 動作テスト")
    print("-" * 40)

    db_path = "data/jrdb.db"
    if os.path.exists(db_path):
        import sqlite3
        db = sqlite3.connect(db_path)
        n_races = db.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        n_entries = db.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        latest = db.execute("SELECT MAX(race_date) FROM races").fetchone()[0]
        db.close()
        print(f"  DB接続: OK")
        print(f"  レース数: {n_races:,}")
        print(f"  エントリー数: {n_entries:,}")
        print(f"  最新日付: {latest}")
    else:
        print(f"  DB接続: SKIP (jrdb.db が見つかりません)")

    model_path = "data/models/prod_model_v16.txt"
    if os.path.exists(model_path):
        try:
            import lightgbm as lgb
            model = lgb.Booster(model_file=model_path)
            print(f"  モデルロード: OK ({model.num_feature()} features)")
        except Exception as e:
            print(f"  モデルロード: ERROR ({e})")
    else:
        print(f"  モデルロード: SKIP (モデルファイルなし)")

    # Next.js ビルドテスト
    print(f"  Next.js: ", end="")
    if os.path.exists("node_modules"):
        print("OK (node_modules あり)")
    else:
        print("npm install が必要")

    # === 完了 ===
    print("\n")
    print("=" * 60)
    if not missing:
        print("  セットアップ完了！")
        print()
        print("  起動コマンド:")
        print("    npm run dev                              # Webアプリ")
        print("    python scripts/production/realtime_bet.py  # 自動投票")
    else:
        print("  セットアップ未完了 — 不足ファイルを配置してください")
        print()
        print("  必要なもの:")
        print("    1. data/jrdb.db (18GB) — 元PCからコピー")
        print("    2. data/models/ フォルダ — 元PCからコピー")
        print("    3. scripts/production/.env — 認証情報を入力")
        print()
        print("  配置後に再度このスクリプトを実行してください。")
    print("=" * 60)

    # コピー用のファイルリスト
    print()
    print("  【元PCからコピーが必要なファイル一覧】")
    print("  " + "-" * 50)
    copy_files = [
        "data/jrdb.db",
        "data/models/prod_config.json",
        "data/models/prod_model_v16.txt",
        "data/models/prod_stats.json",
        "data/models/prod_stats_v16.json",
        "data/models/prod_trio_v22.txt",
        "data/models/prod_trio_config_v22.json",
        "data/models/prod_trio_stats_v22.json",
        "data/models/prod_exotic_v22g.json",
        "data/models/prod_trio_v22g.txt",
        "data/models/prod_umaren_v22g.txt",
        "data/models/prod_trifecta_v22g.txt",
    ]
    for f in copy_files:
        size = ""
        if os.path.exists(f):
            s = os.path.getsize(f)
            if s > 1_000_000_000:
                size = f" ({s/1_000_000_000:.1f}GB)"
            elif s > 1_000_000:
                size = f" ({s/1_000_000:.1f}MB)"
            elif s > 1000:
                size = f" ({s/1000:.0f}KB)"
        print(f"    {f}{size}")


if __name__ == "__main__":
    main()
