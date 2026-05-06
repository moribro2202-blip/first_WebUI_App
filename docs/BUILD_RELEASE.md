# ビルド・デプロイ手順

## 前提条件

- Vercel アカウント（https://vercel.com）
- GitHub リポジトリ連携済み

## ビルド

### ローカルビルド

```bash
# プロダクションビルド
npm run build

# ビルド結果を確認
npm run start
```

### ビルドエラーチェック

```bash
# 型チェック
npx tsc --noEmit

# Lint
npm run lint

# テスト
npm run test
```

## Vercel デプロイ

### 初回セットアップ

1. Vercel にログイン
2. 「New Project」→ GitHub リポジトリを選択
3. 環境変数を設定:
   - `NEXT_PUBLIC_FIREBASE_API_KEY`
   - `NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN`
   - `NEXT_PUBLIC_FIREBASE_PROJECT_ID`
   - `NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET`
   - `NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID`
   - `NEXT_PUBLIC_FIREBASE_APP_ID`
4. 「Deploy」をクリック

### 自動デプロイ

- `main` ブランチへの push で本番デプロイ
- PR 作成時にプレビューデプロイ

### Vercel CLI（オプション）

```bash
# Vercel CLI インストール
npm install -g vercel

# ログイン
vercel login

# プレビューデプロイ
vercel

# 本番デプロイ
vercel --prod
```

## Docker デプロイ（オプション）

### Dockerfile

```dockerfile
FROM node:20-alpine AS base

FROM base AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
```

```bash
# ビルド
docker build -t my-app .

# 実行
docker run -p 3000:3000 my-app
```

## バージョン管理

`package.json` で管理:

```json
{
  "version": "1.0.0"
}
```

### バージョン更新ルール

- メジャー: 破壊的変更（1.0.0 → 2.0.0）
- マイナー: 新機能追加（1.0.0 → 1.1.0）
- パッチ: バグ修正（1.0.0 → 1.0.1）

## リリースチェックリスト

### ビルド前

- [ ] `npm run build` でビルドエラーがないか確認
- [ ] `npx tsc --noEmit` で型エラーがないか確認
- [ ] `npm run lint` でLintエラーがないか確認
- [ ] `npm run test` でテストが通るか確認
- [ ] 環境変数が本番用になっているか確認

### デプロイ後

- [ ] 主要ページの表示確認
- [ ] 主要機能の動作確認
- [ ] Firebase 接続確認
- [ ] レスポンシブ表示確認
- [ ] コンソールエラーがないか確認

### SEO/メタデータ

- [ ] ページタイトル設定済み
- [ ] OGP 画像設定済み
- [ ] favicon 設定済み

## 参考リンク

- [Next.js Deployment](https://nextjs.org/docs/deployment)
- [Vercel Documentation](https://vercel.com/docs)
