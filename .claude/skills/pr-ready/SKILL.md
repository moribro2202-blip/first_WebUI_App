---
name: pr-ready
description: PR作成準備スキル。型チェック、テスト、コミット、PR作成を一括実行。PR準備、プルリクエスト、マージ準備、レビュー依頼時に使用。
---

# PR作成準備スキル

コードの品質チェックからPR作成までを一括で実行します。

## When to Use This Skill

- 実装が完了してPRを作成したい時
- 「/pr-ready」と入力された時
- 「PRを作成して」と依頼された時
- コードをレビューに出す準備をしたい時

## ワークフロー

```
┌──────────────────┐
│ 1. 変更確認       │ git status, git diff で変更内容確認
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. 型チェック     │ npx tsc --noEmit
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 3. Lint          │ npm run lint（設定があれば）
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 4. テスト        │ npm test
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 5. コミット       │ Conventional Commits形式
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 6. プッシュ       │ git push -u origin HEAD
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 7. PR作成        │ gh pr create
└──────────────────┘
```

## 引数

```
/pr-ready                      # フル実行
/pr-ready --skip-test          # テストスキップ
/pr-ready --draft              # ドラフトPRとして作成
/pr-ready --base develop       # ベースブランチ指定
```

| 引数 | 説明 |
|------|------|
| `--skip-test` | テスト実行をスキップ |
| `--skip-lint` | Lintチェックをスキップ |
| `--draft` | ドラフトPRとして作成 |
| `--base <branch>` | マージ先ブランチを指定（デフォルト: main） |
| `--reviewer <user>` | レビュアーを指定 |

## AI Assistant Instructions

### フェーズ1: 変更確認

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

### フェーズ2: 型チェック

```bash
npx tsc --noEmit
```

エラーがある場合:
```
❌ 型チェックエラー

src/components/Button.tsx:15:3
  error TS2322: Type 'string' is not assignable to type 'number'

修正後、再度 /pr-ready を実行してください
```

### フェーズ3: Lint（設定がある場合）

```bash
# package.json に lint スクリプトがあれば実行
npm run lint
```

### フェーズ4: テスト

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

### フェーズ5: コミット

未コミットの変更がある場合:

```bash
git add .
git commit -m "feat: 機能説明

- 変更点1
- 変更点2

🤖 Generated with Claude Code"
```

### フェーズ6: プッシュ

```bash
git push -u origin HEAD
```

### フェーズ7: PR作成

```bash
gh pr create \
  --title "feat: 機能のタイトル" \
  --body "## 概要
この PR では〇〇を実装しました。

## 変更内容
- 変更点1
- 変更点2

## スクリーンショット
（該当する場合）

## テスト
- [x] 型チェック通過
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

## PRテンプレート

```markdown
## 概要
<!-- この PR で何を実現するか -->

## 変更内容
<!-- 箇条書きで変更点を列挙 -->
-

## 関連Issue
<!-- 関連する Issue があれば -->
- closes #

## スクリーンショット
<!-- UI変更がある場合 -->

## テスト
- [ ] 型チェック通過
- [ ] ユニットテスト通過
- [ ] 動作確認完了

## レビューポイント
<!-- レビュアーに特に見てほしい箇所 -->

---
🤖 Generated with Claude Code
```

## 完了時の出力

```
✅ PR作成完了！

📋 サマリー
├─ ブランチ: feature/auth-login → main
├─ コミット: 3件
├─ 変更ファイル: 8件 (+245, -32)
└─ PR: #42

🔗 PR URL: https://github.com/owner/repo/pull/42

📝 チェックリスト
✓ 型チェック通過
✓ テスト通過
✓ Lint通過
✓ プッシュ完了
✓ PR作成完了

💡 次のステップ
- レビュアーにレビュー依頼
- CIの結果を確認
```

## エラー時の対応

### プッシュ拒否

```
❌ プッシュが拒否されました

原因: リモートに新しいコミットがあります

対応:
git pull --rebase origin main
# コンフリクト解決後
/pr-ready
```

### PR作成失敗

```
❌ PR作成に失敗しました

原因: 同じブランチのPRが既に存在します

対応:
1. 既存PRを確認: gh pr view
2. 追加コミットをプッシュ: git push
```

## 関連スキル

- `/dev-flow`: タスク確認から一連の流れ
- `/git-commit`: コミットメッセージ生成
- `/code-review`: PRのレビュー
