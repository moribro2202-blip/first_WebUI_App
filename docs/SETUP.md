# 開発環境セットアップ

## 前提条件

- Windows 11
- Node.js 20.x 以上
- npm または yarn
- Git

## 初回セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd <project-name>
```

### 2. 依存関係のインストール

```bash
npm install
```

### 3. 環境変数の設定

`.env.example` をコピーして `.env.local` を作成:

```bash
cp .env.example .env.local
```

Firebase の設定値を入力:

```
NEXT_PUBLIC_FIREBASE_API_KEY=
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=
NEXT_PUBLIC_FIREBASE_PROJECT_ID=
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
NEXT_PUBLIC_FIREBASE_APP_ID=
```

### 4. 開発サーバーの起動

```bash
npm run dev
```

ブラウザで http://localhost:3000 を開く。

## よく使うコマンド

| コマンド | 説明 |
|----------|------|
| `npm run dev` | 開発サーバー起動 |
| `npm run build` | プロダクションビルド |
| `npm run start` | ビルド後のサーバー起動 |
| `npm run lint` | ESLint 実行 |
| `npm run test` | テスト実行 |
| `npx tsc --noEmit` | 型チェック |

## shadcn/ui コンポーネント追加

```bash
# コンポーネントを追加
npx shadcn@latest add button
npx shadcn@latest add card
npx shadcn@latest add input
npx shadcn@latest add dialog
```

## キャッシュクリア

```bash
# Next.js キャッシュクリア
rm -rf .next

# node_modules 再インストール
rm -rf node_modules
npm install
```

## 次のステップ

- `docs/requirements/functional.md` で実装する機能を確認
- `docs/techstack.md` で使用技術を確認
