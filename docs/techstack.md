

# 技術スタック（Next.js Web App）

## フロントエンド

### コアテクノロジー

-**Next.js** (v15.x) - React フルスタックフレームワーク（App Router）

-**React** (v19.x) - UI ライブラリ

-**TypeScript** (v5.x) - 型付き JavaScript

### ルーティング

-**Next.js App Router** - ファイルベースルーティング

- Server Components / Client Components 対応
- Layouts, Loading, Error UI 対応
- Parallel Routes, Intercepting Routes 対応

### UI コンポーネント

-**Tailwind CSS** (v4.x) - ユーティリティファースト CSS フレームワーク

-**shadcn/ui** - 再利用可能な UI コンポーネント集（Radix UI ベース）

-**lucide-react** - アイコンライブラリ

-**Framer Motion** (v11.x) - アニメーションライブラリ

### 状態管理

-**Zustand** (v5.x) - 軽量状態管理

-**TanStack Query** (v5.x) - サーバー状態管理・キャッシュ

## バックエンド（Firebase）

| サービス                 | 用途                                   |
| ------------------------ | -------------------------------------- |
| Firebase Authentication  | ユーザー認証（メール、Google）         |
| Cloud Firestore          | ユーザーデータ、お気に入り、履歴の保存 |
| Firebase Storage         | ユーザーの写真保存                     |
| Firebase Analytics       | 利用状況分析                           |

### Firebase SDK

-**firebase** (v10.x) - Firebase JavaScript SDK

## フォーム処理

-**React Hook Form** (v7.x) - フォーム状態管理

-**Zod** (v3.x) - スキーマバリデーション

## ユーティリティ

### 日付処理

-**date-fns** (v3.x) - 日付操作ライブラリ

### 認証関連

-**next-auth** (v5.x) - 認証ライブラリ（オプション）

### その他

-**clsx** / **tailwind-merge** - className 結合ユーティリティ

## 開発ツール

-**ESLint** (v9.x) - コード品質管理

-**Prettier** (v3.x) - コードフォーマッター

-**TypeScript** - 型チェック

## テスト

-**Vitest** - ユニットテスト

-**Testing Library** (@testing-library/react) - コンポーネントテスト

-**Playwright** (オプション) - E2Eテスト

## ビルド・デプロイメント

### 開発

-**Next.js Dev Server** - 開発中のホットリロード

### 本番

-**Vercel** - 推奨デプロイ先

-**Docker** (オプション) - コンテナデプロイ

## 対応ブラウザ

- Chrome (最新2バージョン)
- Firefox (最新2バージョン)
- Safari (最新2バージョン)
- Edge (最新2バージョン)

## 特徴

- ファイルベースルーティング（App Router）
- SSR / SSG / ISR 対応
- Server Components によるパフォーマンス最適化
- レスポンシブデザイン
- 型安全性の確保
- アクセシビリティ対応

## プロジェクト構造

```
src/
├── app/                    # Next.js App Router ページ
│   ├── (auth)/            # 認証画面（レイアウトグループ）
│   ├── (main)/            # メインコンテンツ
│   ├── api/               # API Routes
│   ├── layout.tsx         # ルートレイアウト
│   └── page.tsx           # トップページ
├── components/            # 共通コンポーネント
│   ├── ui/               # shadcn/ui コンポーネント
│   └── features/         # 機能別コンポーネント
├── contexts/             # React Context
├── hooks/                # カスタムフック
├── lib/                  # ユーティリティ
│   ├── firebase.ts      # Firebase設定
│   └── utils.ts         # ヘルパー関数
├── stores/               # Zustand ストア
└── types/                # 型定義
```

## 重要な注意事項

1.**技術スタックのバージョン変更は禁止** - 変更が必要な場合は理由を明確にして承認を得ること

2. shadcn/ui は Radix UI ベースのアクセシブルなコンポーネントを提供
3. Firebase の各サービスは Firebase Console で事前に有効化が必要
4. Vercel へのデプロイは GitHub リポジトリ連携が推奨
