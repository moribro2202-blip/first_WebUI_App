---
name: dev-flow
description: 開発フロー統合スキル。タスク確認からPR作成まで一連の開発フローを自動化。feature実装、機能開発、開発開始、PR作成、PR準備、プルリクエスト、マージ準備、レビュー依頼、dev-flow時に使用。
---

# 開発フロー統合スキル

タスク確認 → 実装 → 品質チェック → コミット → PR作成 までの一連の開発フローを統合管理します。

> **Note**: 旧 `/pr-ready` スキルは本スキルに統合されました。`/dev-flow --quick` で同等の機能が使用できます。

## When to Use This Skill

- 新機能の実装を開始する時
- 「/dev-flow」と入力された時
- 「開発フローで進めて」と依頼された時
- 機能実装からPR作成まで一気通貫で行いたい時
- 実装が完了してPRを作成したい時（--quick）
- 「PRを作成して」と依頼された時（--quick）
- コードをレビューに出す準備をしたい時（--quick）

## ワークフロー概要

```
┌─────────────────┐
│ 1. タスク確認    │ docs/tasks/ のToDoを確認・ステータス更新
└───────┬─────────┘  ※ --quick でスキップ
        ▼
┌─────────────────┐
│ 2. 実装準備      │ 要件定義確認・ブランチ作成（必要時）
└───────┬─────────┘  ※ --quick でスキップ
        ▼
┌─────────────────┐
│ 3. 実装         │ コード変更・要件チェックボックス更新
└───────┬─────────┘  ※ --quick でスキップ
        ▼
┌─────────────────┐
│ 4. 変更確認      │ git status, git diff で変更内容確認
└───────┬─────────┘
        ▼
┌─────────────────┐
│ 5. 品質チェック  │ 型チェック・Lint・テスト実行
└───────┬─────────┘
        ▼
┌─────────────────┐
│ 6. コミット      │ Conventional Commits形式で自動生成
└───────┬─────────┘
        ▼
┌─────────────────┐
│ 7. プッシュ      │ git push -u origin HEAD
└───────┬─────────┘
        ▼
┌─────────────────┐
│ 8. PR作成       │ gh pr create
└─────────────────┘
```

## 引数オプション

| 引数 | 説明 |
|------|------|
| `--quick` | タスク確認・実装準備・実装をスキップ（旧 pr-ready 相当） |
| `--skip-test` | テスト実行をスキップ |
| `--skip-lint` | Lintチェックをスキップ |
| `--no-pr` | PR作成をスキップ（コミットまで） |
| `--no-commit` | コミットをスキップ（品質チェックまで） |
| `--draft` | ドラフトPRとして作成 |
| `--base <branch>` | マージ先ブランチを指定（デフォルト: main） |
| `--reviewer <user>` | レビュアーを指定 |

## 使用例

```bash
# フルフロー実行（タスク確認から）
/dev-flow

# PR準備のみ（旧 /pr-ready 相当）
/dev-flow --quick

# テストスキップ
/dev-flow --skip-test
/dev-flow --quick --skip-test

# コミットまで（PRなし）
/dev-flow --no-pr
/dev-flow --quick --no-pr

# ドラフトPR作成
/dev-flow --quick --draft

# ベースブランチ指定
/dev-flow --quick --base develop

# レビュアー指定
/dev-flow --quick --reviewer @username
```

## AI Assistant Instructions

### フェーズ1: タスク確認（--quick でスキップ）

1. `docs/tasks/` 配下のタスクファイルを確認
2. 現在作業中のタスクを特定
3. ステータスを 🟡 進行中 に更新
4. 依存関係を確認

```bash
ls docs/tasks/
```

### フェーズ2: 実装準備（--quick でスキップ）

1. `docs/requirements/functional.md` で要件を確認
2. 必要に応じてfeatureブランチを作成

```bash
git checkout -b feature/機能名
```

### フェーズ3: 実装（--quick でスキップ）

1. 要件定義に基づいてコードを実装
2. `docs/requirements/functional.md` の該当チェックボックスを更新
3. 実装完了後、タスクファイルのToDoも更新

### フェーズ4: 変更確認

```bash
# 変更内容を確認
git status
git diff --stat

# コミット履歴確認（ブランチ分岐後）
git log main..HEAD --oneline
```

変更がない場合は終了:
```
ℹ️ コミットする変更がありません
```

### フェーズ5: 品質チェック（--no-commit でここまで）

#### 5-1. 型チェック

```bash
npx tsc --noEmit
```

エラーがある場合:
```
❌ 型チェックエラー

src/components/Button.tsx:15:3
  error TS2322: Type 'string' is not assignable to type 'number'

修正後、再度実行してください
```

#### 5-2. Lint（--skip-lint でスキップ可）

```bash
# package.json に lint スクリプトがあれば実行
npm run lint
```

#### 5-3. テスト（--skip-test でスキップ可）

```bash
npm test
# または
npx jest --passWithNoTests
```

テスト失敗時:
```
❌ テスト失敗

FAIL src/utils/format.test.ts
  ● formatDate › should format date correctly

修正するか、--skip-test で続行できます
```

### フェーズ6: コミット（--no-pr でここまで）

未コミットの変更がある場合:

```bash
git add .
git commit -m "feat: 機能説明

- 変更点1
- 変更点2

🤖 Generated with Claude Code"
```

### フェーズ7: プッシュ

```bash
git push -u origin HEAD
```

### フェーズ8: PR作成

```bash
gh pr create \
  --title "feat: 機能のタイトル" \
  --body "## 概要
この PR では〇〇を実装しました。

## 変更内容
- 変更点1
- 変更点2

## 関連Issue
- closes #

## スクリーンショット
（該当する場合）

## テスト
- [x] 型チェック通過
- [x] Lint通過
- [x] テスト通過
- [ ] 動作確認

## レビューポイント
- 確認してほしい箇所

🤖 Generated with Claude Code"
```

ドラフトPRの場合:
```bash
gh pr create --draft ...
```

レビュアー指定:
```bash
gh pr create --reviewer @username ...
```

ベースブランチ指定:
```bash
gh pr create --base develop ...
```

## 進捗報告フォーマット

各フェーズ完了時に以下の形式で報告:

```
✅ フェーズ1: タスク確認 完了
   - タスク: 001_認証機能
   - ステータス: 🟡 進行中

✅ フェーズ2: 実装準備 完了
   - ブランチ: feature/auth-login

🔄 フェーズ3: 実装 進行中
   ...
```

## 完了時の出力

```
🎉 開発フロー完了！

📋 サマリー
├─ タスク: 001_認証機能（--quickの場合は省略）
├─ ブランチ: feature/auth-login → main
├─ コミット: 3件
├─ 変更ファイル: 8件 (+245, -32)
└─ PR: #42

🔗 PR URL: https://github.com/owner/repo/pull/42

📝 チェックリスト
✓ 型チェック通過
✓ Lint通過
✓ テスト通過
✓ プッシュ完了
✓ PR作成完了

💡 次のステップ
- レビュアーにレビュー依頼
- CIの結果を確認
```

## エラー時の対応

### 型チェックエラー

```
❌ 型チェックでエラーが発生しました
   エラー内容: [詳細]

   修正してから再度実行してください
```

### テスト失敗

```
❌ テストが失敗しました
   失敗したテスト: [テスト名]

   修正するか、--skip-test オプションで続行できます
```

### プッシュ拒否

```
❌ プッシュが拒否されました

原因: リモートに新しいコミットがあります

対応:
git pull --rebase origin main
# コンフリクト解決後
/dev-flow --quick
```

### PR作成失敗

```
❌ PR作成に失敗しました

原因: 同じブランチのPRが既に存在します

対応:
1. 既存PRを確認: gh pr view
2. 追加コミットをプッシュ: git push
```

## 禁止事項

- mainブランチへの直接コミット
- テスト未実行でのPR作成（明示的スキップ除く）
- 要件定義にない機能の追加
- コミットメッセージの英語化（指示がない限り日本語）

## 関連スキル

- `/git-commit`: コミットメッセージ生成
- `/feature-start`: 新機能開始（ブランチ作成・タスク分割）
- `/hotfix`: 緊急修正フロー
- `/code-review`: PRのレビュー
- `/debugging-guide`: エラー対応
