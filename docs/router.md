

# Next.js App Router ベストプラクティス実装ルール

## 1. ルーティングとファイル構造

### ディレクトリ構造例

```
src/
├── app/                    # Next.js App Router ページ
│   ├── (auth)/            # 認証画面（レイアウトグループ）
│   │   ├── sign-in/
│   │   │   └── page.tsx
│   │   ├── sign-up/
│   │   │   └── page.tsx
│   │   └── layout.tsx
│   ├── (main)/            # メインコンテンツ
│   │   ├── page.tsx       # ホーム（/）
│   │   ├── search/
│   │   │   └── page.tsx
│   │   ├── favorites/
│   │   │   └── page.tsx
│   │   ├── profile/
│   │   │   └── page.tsx
│   │   ├── settings/
│   │   │   └── page.tsx
│   │   └── layout.tsx
│   ├── api/               # API Routes
│   │   └── auth/
│   │       └── route.ts
│   ├── [id]/              # 動的ルート
│   │   └── page.tsx
│   ├── layout.tsx         # ルートレイアウト
│   ├── loading.tsx        # グローバルローディング
│   ├── error.tsx          # グローバルエラー
│   └── not-found.tsx      # 404ページ
│
├── components/            # Reactコンポーネント
│   ├── ui/               # shadcn/ui コンポーネント
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── input.tsx
│   │   └── dialog.tsx
│   ├── features/         # 機能別コンポーネント
│   │   ├── auth/
│   │   ├── home/
│   │   └── profile/
│   └── layouts/          # レイアウトコンポーネント
│       ├── header.tsx
│       ├── sidebar.tsx
│       └── footer.tsx
│
├── hooks/                # カスタムフック
│   ├── use-auth.ts
│   ├── use-firestore.ts
│   └── use-storage.ts
│
├── contexts/             # React Context
│   └── auth-context.tsx
│
├── stores/               # Zustand ストア
│   ├── use-user-store.ts
│   └── use-app-store.ts
│
├── lib/                  # ユーティリティ関数
│   ├── firebase.ts      # Firebase設定
│   ├── constants.ts     # 定数
│   └── utils.ts         # ヘルパー関数
│
├── types/                # 型定義
│   ├── user.ts
│   └── api.ts
│
└── assets/               # 静的アセット
    ├── images/
    └── fonts/
```

### 命名規則

- ページ: `page.tsx`
- レイアウト: `layout.tsx`
- ローディング: `loading.tsx`
- エラー: `error.tsx`
- 404ページ: `not-found.tsx`
- 動的ルート: `[param]/page.tsx` または `[...param]/page.tsx`
- ルートグループ: `(group-name)/`
- API Routes: `route.ts`

## 2. レイアウト設計

### ルートレイアウト

```typescript
// app/layout.tsx
import type { Metadata } from "next";
import { AuthProvider } from "@/contexts/auth-context";
import { QueryProvider } from "@/contexts/query-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "App Name",
  description: "App description",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        <QueryProvider>
          <AuthProvider>
            {children}
          </AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
```

### メインレイアウト（サイドバー + ヘッダー）

```typescript
// app/(main)/layout.tsx
import { Header } from "@/components/layouts/header";
import { Sidebar } from "@/components/layouts/sidebar";

export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <div className="flex flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
```

## 3. データフェッチング

### Server Components でのデータ取得

```typescript
// app/(main)/page.tsx (Server Component)
import { collection, getDocs } from "firebase/firestore";
import { db } from "@/lib/firebase";
import { ItemList } from "@/components/features/home/item-list";

export default async function HomePage() {
  const snapshot = await getDocs(collection(db, "items"));
  const items = snapshot.docs.map((doc) => ({
    id: doc.id,
    ...doc.data(),
  }));

  return <ItemList items={items} />;
}
```

### Client Components + TanStack Query

```typescript
// hooks/use-items.ts
"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { collection, getDocs, addDoc } from "firebase/firestore";
import { db } from "@/lib/firebase";

export function useItems() {
  return useQuery({
    queryKey: ["items"],
    queryFn: async () => {
      const snapshot = await getDocs(collection(db, "items"));
      return snapshot.docs.map((doc) => ({
        id: doc.id,
        ...doc.data(),
      }));
    },
  });
}

export function useCreateItem() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (data: ItemData) => {
      const docRef = await addDoc(collection(db, "items"), data);
      return { id: docRef.id, ...data };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["items"] });
    },
  });
}
```

### コンポーネントでの使用

```typescript
// components/features/home/item-list.tsx
"use client";

import { useItems } from "@/hooks/use-items";
import { ItemCard } from "./item-card";
import { Skeleton } from "@/components/ui/skeleton";

export function ItemList() {
  const { data: items, isLoading, error } = useItems();

  if (isLoading) {
    return (
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-48 w-full" />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-destructive">エラーが発生しました</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
      {items?.map((item) => (
        <ItemCard key={item.id} item={item} />
      ))}
    </div>
  );
}
```

## 4. ナビゲーション操作

### プログラマティックナビゲーション

```typescript
"use client";

import { useRouter } from "next/navigation";

export function MyComponent() {
  const router = useRouter();

  // 画面遷移
  router.push("/profile");
  router.push("/items/123");

  // 置き換え（戻るボタンで戻れない）
  router.replace("/");

  // 戻る
  router.back();
}
```

### Link コンポーネント

```typescript
import Link from "next/link";

<Link href="/profile">
  プロフィールへ
</Link>

<Link href={`/items/${item.id}`}>
  詳細を見る
</Link>
```

## 5. 認証ガード

### ミドルウェアによる認証保護

```typescript
// middleware.ts
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const protectedPaths = ["/", "/search", "/favorites", "/profile", "/settings"];
const authPaths = ["/sign-in", "/sign-up"];

export function middleware(request: NextRequest) {
  const token = request.cookies.get("auth-token")?.value;
  const { pathname } = request.nextUrl;

  // 未認証ユーザーを認証画面にリダイレクト
  if (!token && protectedPaths.some((path) => pathname.startsWith(path))) {
    return NextResponse.redirect(new URL("/sign-in", request.url));
  }

  // 認証済みユーザーをメインページにリダイレクト
  if (token && authPaths.some((path) => pathname.startsWith(path))) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
```

## 6. パフォーマンス最適化

### 画像最適化

```typescript
import Image from "next/image";

<Image
  src={imageUrl}
  alt="説明テキスト"
  width={200}
  height={200}
  className="rounded-lg object-cover"
  placeholder="blur"
  blurDataURL={blurHash}
/>
```

### 動的インポート

```typescript
import dynamic from "next/dynamic";

const HeavyComponent = dynamic(() => import("@/components/heavy-component"), {
  loading: () => <Skeleton className="h-64 w-full" />,
});
```

### メモ化

```typescript
import { memo, useMemo, useCallback } from "react";

const ItemCard = memo(({ item }: { item: Item }) => {
  // コンポーネント内容
});
```

## 7. エラーハンドリング

### Error Boundary

```typescript
// app/error.tsx
"use client";

import { Button } from "@/components/ui/button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 p-4">
      <h2 className="text-lg font-bold">エラーが発生しました</h2>
      <p className="text-muted-foreground">{error.message}</p>
      <Button onClick={reset}>再試行</Button>
    </div>
  );
}
```

### 404ページ

```typescript
// app/not-found.tsx
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center">
      <h2 className="mb-4 text-xl font-bold">ページが見つかりません</h2>
      <Link href="/" className="text-primary hover:underline">
        ホームに戻る
      </Link>
    </div>
  );
}
```

## 8. 型安全性

### TypeScript 設定

```json
{
  "compilerOptions": {
    "strict": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  }
}
```

### ルートパラメータの型定義

```typescript
// app/items/[id]/page.tsx
type Props = {
  params: Promise<{ id: string }>;
};

export default async function ItemDetailPage({ params }: Props) {
  const { id } = await params;
  // ...
}
```

## 9. 環境変数

### 設定

```env
NEXT_PUBLIC_FIREBASE_API_KEY=xxx
NEXT_PUBLIC_FIREBASE_PROJECT_ID=xxx
```

### 使用

```typescript
// クライアント側（NEXT_PUBLIC_ プレフィックス必須）
const apiKey = process.env.NEXT_PUBLIC_FIREBASE_API_KEY;

// サーバー側のみ
const secretKey = process.env.FIREBASE_ADMIN_KEY;
```

## 10. メンテナンス

### 依存関係

- 定期的に依存パッケージを更新
- `npm outdated` でバージョン確認

### パフォーマンスモニタリング

- Firebase Analytics で利用状況を分析
- Vercel Analytics でパフォーマンスを監視
- Lighthouse でスコアを定期チェック

## 重要な注意事項

1.**ファイルベースルーティング**を厳守 - URLとファイルパスを一致させる

2.**認証ガード**はミドルウェアまたはレイアウトで実装

3.**データフェッチングは Server Components を優先**、クライアント側は TanStack Query を使用

4.**画像は next/image** を使用して最適化

5.**Server Components と Client Components の境界**を意識する（"use client" は必要な箇所のみ）
