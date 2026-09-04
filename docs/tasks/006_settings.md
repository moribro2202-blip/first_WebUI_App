# Task 6: 設定・仕上げ

## 概要

設定画面とダークモード、全体の仕上げ。

## タスク

- [x] 設定画面（`/settings`）
  - Claude API キーの入力・保存（localStorage に暗号化保存 or 環境変数案内）
  - ダークモード切り替え（next-themes）
- [x] ダークモード対応
  - next-themes 導入
  - 全画面のダークモード対応確認
- [x] 全体仕上げ
  - loading.tsx（グローバルローディング）
  - error.tsx（グローバルエラー）
  - not-found.tsx（404ページ）
  - レスポンシブ対応確認

## 作成ファイル

```
src/
├── app/
│   ├── settings/page.tsx       （設定画面実装）
│   ├── loading.tsx
│   ├── error.tsx
│   └── not-found.tsx
└── components/features/settings/
    ├── api-key-form.tsx
    └── theme-toggle.tsx
```

## 完了条件

- APIキーを設定画面から入力・保存できる
- ダークモード切り替えが全画面で動作する
