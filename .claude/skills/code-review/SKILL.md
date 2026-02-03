---
name: code-review
description: コードレビュースキル。PRの差分取得、コード分析、レビューコメント作成を一括実行。レビュー、PR確認、コードチェック時に使用。
---

# コードレビュースキル

Pull Request のコードレビューを効率的に実行します。

## When to Use This Skill

- PRをレビューする時
- 「/code-review」と入力された時
- 「PRをレビューして」と依頼された時
- コードの品質チェックをしたい時

## ワークフロー

```
┌──────────────────┐
│ 1. PR情報取得     │ PR詳細・差分を取得
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. 変更分析       │ 変更ファイル・行数を分析
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 3. コード品質     │ 型・パターン・セキュリティ確認
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 4. ロジック確認   │ ビジネスロジック・エッジケース
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 5. レビュー作成   │ コメント・承認/要修正判定
└──────────────────┘
```

## 引数

```
/code-review #123                  # PR番号指定
/code-review                       # 現在のブランチのPR
/code-review --focus security      # セキュリティ重点
/code-review --focus performance   # パフォーマンス重点
```

| 引数 | 説明 |
|------|------|
| `#<number>` | レビューするPR番号 |
| `--focus <area>` | 重点チェック領域（security/performance/logic） |
| `--quick` | 簡易レビュー |
| `--strict` | 厳格レビュー |

## AI Assistant Instructions

### フェーズ1: PR情報取得

```bash
# PR詳細を取得
gh pr view 123

# 差分を取得
gh pr diff 123

# 変更ファイル一覧
gh pr view 123 --json files --jq '.files[].path'

# PRコメント確認
gh api repos/{owner}/{repo}/pulls/123/comments
```

### フェーズ2: 変更分析

**分析項目:**

| 項目 | 確認内容 |
|------|----------|
| ファイル数 | 変更ファイルの数と種類 |
| 変更行数 | 追加/削除行数 |
| 影響範囲 | 変更の影響を受ける機能 |
| 依存関係 | 新規/変更された依存関係 |

```
📊 変更分析

ファイル: 8件
├─ コンポーネント: 3件
├─ フック: 2件
├─ ユーティリティ: 1件
├─ テスト: 2件
└─ 設定: 0件

変更量: +245行 / -32行
影響範囲: 認証機能、ホーム画面
```

### フェーズ3: コード品質チェック

**チェック項目:**

#### 型安全性
- [ ] any 型の使用を避けている
- [ ] 適切な型定義がある
- [ ] null/undefined の適切な処理

#### コーディング規約
- [ ] 命名規則に従っている
- [ ] 一貫したコードスタイル
- [ ] 適切なコメント

#### パターン・設計
- [ ] 既存パターンとの一貫性
- [ ] 適切な責務分離
- [ ] 再利用可能な設計

#### セキュリティ
- [ ] 入力値の検証
- [ ] 機密情報の露出なし
- [ ] XSS/インジェクション対策

#### パフォーマンス
- [ ] 不要な再レンダリングなし
- [ ] 適切なメモ化
- [ ] 効率的なデータ取得

### フェーズ4: ロジック確認

**確認項目:**

- [ ] 要件を満たしている
- [ ] エッジケースの処理
- [ ] エラーハンドリング
- [ ] テストカバレッジ

### フェーズ5: レビュー作成

**レビューコメント分類:**

| ラベル | 意味 | 対応 |
|--------|------|------|
| `[必須]` | 修正必須 | マージ前に修正が必要 |
| `[推奨]` | 修正推奨 | 可能であれば修正 |
| `[質問]` | 質問 | 説明を求める |
| `[提案]` | 提案 | 検討してほしい改善案 |
| `[称賛]` | 良い点 | 良いコードへのコメント |

**コメント例:**

```markdown
### [必須] null チェックが必要です

`src/hooks/useAuth.ts:42`

```typescript
// 現在のコード
const user = data.user;
return user.name;

// 提案
const user = data?.user;
return user?.name ?? 'Unknown';
```

`data.user` が undefined の場合にクラッシュする可能性があります。
```

```markdown
### [推奨] useMemo の使用を検討してください

`src/components/UserList.tsx:28`

```typescript
// 現在のコード
const sortedUsers = users.sort((a, b) => a.name.localeCompare(b.name));

// 提案
const sortedUsers = useMemo(
  () => users.sort((a, b) => a.name.localeCompare(b.name)),
  [users]
);
```

毎回のレンダリングでソートが実行されています。
```

```markdown
### [称賛] 良いエラーハンドリングです！

`src/services/api.ts:55`

try-catch でエラーを適切にキャッチし、ユーザーフレンドリーなメッセージに変換している点が良いです。
```

## レビュー結果テンプレート

```markdown
## コードレビュー結果

### 概要
PR #123: 認証機能の実装

### 総合評価: ✅ 承認 / 🔄 要修正 / ❌ 却下

### サマリー
- 変更ファイル: 8件
- 変更行数: +245 / -32
- コメント数: 5件（必須: 1, 推奨: 2, 質問: 1, 称賛: 1）

### 良い点
- 型定義が適切
- テストカバレッジが十分
- エラーハンドリングが丁寧

### 要修正項目
1. [必須] src/hooks/useAuth.ts:42 - null チェック追加
2. [推奨] src/components/UserList.tsx:28 - useMemo 使用
3. [推奨] src/utils/format.ts:15 - 定数を抽出

### 質問
- src/services/api.ts:30 のタイムアウト値の根拠は？

### 結論
必須項目を修正後、承認予定です。
```

## GitHub へのコメント投稿

```bash
# 全体コメント
gh pr review 123 --comment --body "レビューコメント"

# 承認
gh pr review 123 --approve --body "LGTM!"

# 要修正
gh pr review 123 --request-changes --body "修正をお願いします"

# 特定行へのコメント
gh api repos/{owner}/{repo}/pulls/123/comments \
  -f body="コメント内容" \
  -f path="src/file.ts" \
  -f line=42 \
  -f side="RIGHT"
```

## 完了時の出力

```
📝 レビュー完了！

PR #123: 認証機能の実装
評価: 🔄 要修正

📋 コメントサマリー
├─ 必須修正: 1件
├─ 推奨修正: 2件
├─ 質問: 1件
└─ 称賛: 1件

🔗 PR: https://github.com/owner/repo/pull/123

💬 投稿したコメント:
- useAuth.ts:42 - [必須] null チェック
- UserList.tsx:28 - [推奨] useMemo
- format.ts:15 - [推奨] 定数抽出
```

## 関連スキル

- `/pr-ready`: PR作成
- `/dev-flow`: 開発フロー
- `/debugging-guide`: 問題調査
