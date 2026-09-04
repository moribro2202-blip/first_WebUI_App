# Task 1: プロジェクト基盤・レイアウト

## 概要

認証なしのシンプルな構成でメインレイアウトを構築する。

## タスク

- [ ] `layout.tsx` を競馬AIアプリ用に更新（lang="ja"、メタデータ）
- [ ] メインレイアウト作成（ヘッダー + サイドナビ）
  - ヘッダー: アプリ名
  - サイドナビ: ダッシュボード / 予想 / 履歴 / 設定
- [ ] ルーティング構造作成
  - `/` - ダッシュボード
  - `/predict` - レース予想（入力 + 結果表示）
  - `/history` - 予想履歴
  - `/settings` - 設定
- [ ] データ永続化の基盤（Firestore or localStorage）
- [ ] TanStack Query Provider 設定

## 作成ファイル

```
src/
├── app/
│   ├── layout.tsx          （更新）
│   ├── page.tsx            （ダッシュボードへ）
│   ├── predict/page.tsx
│   ├── history/page.tsx
│   └── settings/page.tsx
├── components/
│   └── layouts/
│       ├── header.tsx
│       └── sidebar.tsx
└── lib/
    └── query-provider.tsx
```

## 完了条件

- 各ページに遷移できる
- サイドナビでページ切り替えができる
