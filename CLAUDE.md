# CLAUDE.md

このファイルは、Claude Code（claude.ai/code）がこのリポジトリで作業する際のガイドラインです。

## プロジェクト概要

React Native/Expo モバイルアプリケーションプロジェクト（iOS/Android）

## 重要ルール

- **既存UIの変更は事前承認が必須**
- **技術スタックのバージョン変更禁止**
- **要件に記載のない機能追加は禁止**
- **アイコンは Lucide（lucide-react-native）のみ使用**

詳細は各ドキュメントを参照。

## 実装ルール

1. 実装前に `docs/requirements/functional.md` の該当機能を確認
2. チェックボックス（- [ ]）が付いた項目のみ実装対象
3. 実装完了後、該当チェックボックスを `- [x]` に更新

## ドキュメント

### 場面別リファレンス

| 場面                   | 参照先                              |
| ---------------------- | ----------------------------------- |
| 開発環境を構築する     | `docs/SETUP.md`                   |
| タスクを分割する       | `docs/tasks/000_overview.md`      |
| 機能を実装する         | `docs/requirements/functional.md` |
| UIを作成する           | `docs/uiux.md`                    |
| ルーティングを追加する | `docs/router.md`                  |
| Firebaseを使う         | `docs/firebase.md`                |
| ビルド・リリースする   | `docs/BUILD_RELEASE.md`           |
| エラーで困った         | `docs/TROUBLESHOOTING.md`         |

### ドキュメント一覧

| ドキュメント                | 内容                     |
| --------------------------- | ------------------------ |
| `docs/SETUP.md`           | 開発環境セットアップ     |
| `docs/BUILD_RELEASE.md`   | ビルド・リリース手順     |
| `docs/TROUBLESHOOTING.md` | トラブルシューティング   |
| `docs/requirements/`      | 要件定義書               |
| `docs/tasks/`             | タスク管理・ToDo         |
| `docs/techstack.md`       | 技術スタック・バージョン |
| `docs/router.md`          | ルーティング規約         |
| `docs/uiux.md`            | UI/UX設計ルール          |
| `docs/firebase.md`        | Firebase実装ガイド       |
| `docs/coding-rules.md`    | コーディング規約         |

## 環境変数

```
EXPO_PUBLIC_FIREBASE_API_KEY
EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN
EXPO_PUBLIC_FIREBASE_PROJECT_ID
EXPO_PUBLIC_FIREBASE_STORAGE_BUCKET
EXPO_PUBLIC_FIREBASE_MESSAGING_SENDER_ID
EXPO_PUBLIC_FIREBASE_APP_ID
```

## 知見蓄積のサイクル

- 他の場面でも発生し得る問題や効率化のノウハウを得た場合は、**必ず回答の最後に知見をまとめ、ルール更新を提案する**
- 新規にルールを作成した場合は、下の「ルールファイルの全体像」に追記する
- 提案されたルール改善は、ユーザー承認後に反映する

### 知見まとめの形式

```
---
📝 **知見メモ**
- [発見した問題/ノウハウ]

💡 **ルール改善提案**
- [具体的な改善案]
- 対象ファイル: [CLAUDE.md / docs/xxx.md / .claude/skills/xxx]
---
```

## ルールファイルの全体像

| ファイル                            | 種類     | 説明                             |
| ----------------------------------- | -------- | -------------------------------- |
| `CLAUDE.md`                       | メイン   | プロジェクト全体のガイドライン   |
| `docs/coding-rules.md`            | コード   | コーディング規約                 |
| `docs/uiux.md`                    | デザイン | UI/UX設計ルール                  |
| `docs/TROUBLESHOOTING.md`         | 運用     | エラー対処法                     |
| `.claude/skills/dev-flow/`          | スキル   | 開発フロー統合（実装→コミット→PR）※旧pr-ready統合 |
| `.claude/skills/feature-start/`     | スキル   | 新機能開始（ブランチ→タスク分割）※旧task-split統合 |
| `.claude/skills/git-commit/`        | スキル   | コミットメッセージ生成           |
| `.claude/skills/hotfix/`            | スキル   | 緊急修正（hotfixブランチ→修正→即PR） |
| `.claude/skills/release/`           | スキル   | リリース統合（ビルド→審査→変更履歴）※旧appstore-review統合 |
| `.claude/skills/code-review/`       | スキル   | コードレビュー（PR差分→分析→コメント） |
| `.claude/skills/revenuecat-setup/`  | スキル   | RevenueCat + App Store Connect 課金設定 |
| `.claude/skills/debugging-guide/`   | スキル   | デバッグ・トラブルシューティング |
| `.claude/skills/uiux-test/`         | スキル   | UI/UXテスト作成ガイド            |
| `.claude/skills/skill-name/`        | スキル   | スキル作成ガイド                 |

> ルールの説明を踏まえ、必要と判断したルールは積極的に事前確認すること。
>
