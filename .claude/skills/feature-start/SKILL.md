---
name: feature-start
description: 新機能開発開始スキル。ブランチ作成からタスク分割、ToDoリスト作成まで一括実行。feature開始、新機能、開発開始、ブランチ作成時に使用。
---

# 新機能開発開始スキル

新しい機能の開発を始める際の初期セットアップを自動化します。

## When to Use This Skill

- 新しい機能の実装を始める時
- 「/feature-start」と入力された時
- 「新機能を始めたい」と依頼された時
- featureブランチを作成してタスク分割したい時

## ワークフロー

```
┌──────────────────┐
│ 1. 要件確認       │ docs/requirements/functional.md を確認
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. ブランチ作成   │ feature/機能名 ブランチを作成
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 3. タスク分割     │ 機能を小タスクに分解
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 4. ToDoファイル作成│ docs/tasks/XXX_機能名.md を作成
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 5. 概要更新       │ docs/tasks/000_overview.md を更新
└──────────────────┘
```

## 引数

```
/feature-start <機能名>
/feature-start 認証機能
/feature-start --no-branch ホーム画面    # ブランチ作成スキップ
```

| 引数 | 説明 |
|------|------|
| `<機能名>` | 実装する機能の名前（必須） |
| `--no-branch` | ブランチ作成をスキップ |
| `--from-requirements` | 要件定義から自動抽出 |

## AI Assistant Instructions

### フェーズ1: 要件確認

1. `docs/requirements/functional.md` を読み込む
2. 該当機能のセクションを特定
3. 実装すべき項目（チェックボックス未完了）を洗い出す

```bash
# 要件定義を確認
cat docs/requirements/functional.md
```

### フェーズ2: ブランチ作成

1. 現在のブランチを確認
2. mainから最新を取得
3. featureブランチを作成

```bash
git checkout main
git pull origin main
git checkout -b feature/機能名
```

**命名規則:**
- `feature/auth-login` - 認証ログイン
- `feature/home-screen` - ホーム画面
- `feature/search-filter` - 検索フィルター

### フェーズ3: タスク分割

要件を以下の粒度で分割:

1. **セットアップ系**: 設定、Context作成、型定義
2. **UI実装系**: 画面、コンポーネント作成
3. **機能実装系**: ロジック、API連携
4. **テスト系**: ユニットテスト、E2Eテスト

**粒度の目安:**
- 1タスク = 1-2時間で完了できる量
- 具体的で検証可能な内容

```
❌ 悪い例: 「認証機能を実装」
✅ 良い例:
  - Firebase Authentication 設定
  - AuthContext 作成
  - サインイン画面 UI
  - サインインロジック実装
```

### フェーズ4: ToDoファイル作成

`docs/tasks/` に新規ファイルを作成:

```markdown
# XXX: 機能名

## ステータス: 🔴 未着手

## 参照
- docs/requirements/functional.md#セクション名

## 依存関係
- 依存先: [先に完了すべきタスク番号]
- 依存元: [このタスク完了後に着手可能なタスク]

## ToDo

### セットアップ
- [ ] 必要なパッケージインストール
- [ ] 型定義ファイル作成

### UI実装
- [ ] 画面コンポーネント作成
- [ ] スタイリング

### 機能実装
- [ ] ロジック実装
- [ ] API連携

### テスト
- [ ] ユニットテスト
- [ ] 動作確認

## メモ
- [実装時の注意点など]
```

### フェーズ5: 概要更新

`docs/tasks/000_overview.md` を更新:

1. 機能一覧テーブルに追加
2. 依存関係図を更新

## 完了時の出力

```
🚀 新機能開発準備完了！

📋 セットアップ内容
├─ ブランチ: feature/auth-login
├─ タスクファイル: docs/tasks/005_認証機能.md
├─ タスク数: 12個
└─ 推定作業量: 中規模

📝 次のステップ
1. docs/tasks/005_認証機能.md を確認
2. 最初のタスクから順に実装開始
3. 完了したら /dev-flow でコミット・PR作成

💡 ヒント: /dev-flow --quick で素早くコミットできます
```

## エラー時の対応

### ブランチが既に存在

```
⚠️ ブランチ feature/xxx は既に存在します

選択肢:
1. 既存ブランチに切り替え: git checkout feature/xxx
2. 別名で作成: /feature-start xxx-v2
```

### 要件定義が見つからない

```
❌ docs/requirements/functional.md に該当機能が見つかりません

対応:
1. 要件定義を先に追加してください
2. または --from-scratch オプションで空のタスクファイルを作成
```

## 関連スキル

- `/task-split`: タスク分割の詳細ルール
- `/dev-flow`: 実装からPR作成まで
- `/git-commit`: コミットメッセージ生成
