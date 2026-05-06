

# UI/UX 設計・実装ルール（Next.js Web App）

## 1. デザインシステム

### 重要度: 最高

- Tailwind CSS をベースとしたスタイリング
- shadcn/ui コンポーネントを活用

-**既存の UI は承認なしでの変更を禁止**

- コンポーネントのカスタマイズは最小限に抑える

```typescript
// 良い例：Tailwind CSS を使用
<div className="flex flex-1 items-center justify-center p-4">
  <p className="text-lg font-bold">Hello</p>
</div>

// 悪い例：インラインスタイル
<div style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
  <p style={{ fontSize: 18, fontWeight: 'bold' }}>Hello</p>
</div>
```

## 2. スタイリング規約

### 重要度: 高

### Tailwind CSS の使用

- ユーティリティクラスを優先的に使用
- CSS Modules は特殊なケースのみ使用
- className の結合には `cn()` ユーティリティを使用

```typescript
// 良い例：Tailwind CSS
<div className="flex flex-row items-center gap-2 rounded-lg bg-white p-4">
  <p className="text-base text-gray-800">タイトル</p>
</div>

// cn() ユーティリティの使用
import { cn } from "@/lib/utils";

<div className={cn("rounded-lg p-4", isActive && "bg-primary text-white")}>
```

### 色の定義

```css
/* globals.css で CSS Variables を使用 */
:root {
  --background: 0 0% 100%;
  --foreground: 222.2 84% 4.9%;
  --primary: 222.2 47.4% 11.2%;
  --secondary: 210 40% 96.1%;
  --destructive: 0 84.2% 60.2%;
  --muted: 210 40% 96.1%;
  --accent: 210 40% 96.1%;
}

.dark {
  --background: 222.2 84% 4.9%;
  --foreground: 210 40% 98%;
  /* ... */
}
```

## 3. レスポンシブデザイン

### 重要度: 高

- モバイルファーストでデザイン
- Tailwind のブレークポイントを使用

```typescript
// 良い例：レスポンシブ対応
<div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
  {items.map((item) => (
    <Card key={item.id}>{item.title}</Card>
  ))}
</div>

// テキストサイズのレスポンシブ
<h1 className="text-2xl font-bold md:text-3xl lg:text-4xl">
  タイトル
</h1>
```

### ブレークポイント

| プレフィックス | 最小幅 | 用途 |
|---------------|--------|------|
| `sm:` | 640px | 小型タブレット |
| `md:` | 768px | タブレット |
| `lg:` | 1024px | デスクトップ |
| `xl:` | 1280px | 大型デスクトップ |
| `2xl:` | 1536px | 超大型画面 |

## 4. アクセシビリティ

### 重要度: 高

- セマンティックHTMLを使用
- ARIA属性を適切に設定
- キーボードナビゲーション対応

```typescript
// 良い例
<button
  aria-label="プロフィールを編集"
  onClick={handleEdit}
>
  <Pencil className="h-4 w-4" />
  <span>編集</span>
</button>

// 画像のアクセシビリティ
<Image
  src={imageUrl}
  alt="ユーザーのプロフィール画像"
  width={100}
  height={100}
/>

// フォームのラベル
<Label htmlFor="email">メールアドレス</Label>
<Input id="email" type="email" />
```

## 5. アニメーションとトランジション

### 重要度: 中

- Tailwind の transition ユーティリティまたは Framer Motion を使用
- 過度なアニメーションを避ける

```typescript
// Tailwind transition
<button className="transition-colors hover:bg-primary/90">
  ボタン
</button>

// Framer Motion
import { motion } from "framer-motion";

<motion.div
  initial={{ opacity: 0, y: 20 }}
  animate={{ opacity: 1, y: 0 }}
  transition={{ duration: 0.3 }}
>
  コンテンツ
</motion.div>
```

## 6. フォーム設計

### 重要度: 高

- React Hook Form + Zod でバリデーション
- エラーメッセージは明確に表示
- shadcn/ui の Form コンポーネントを活用

```typescript
"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const schema = z.object({
  email: z.string().email("有効なメールアドレスを入力してください"),
  password: z.string().min(8, "パスワードは8文字以上です"),
});

export function LoginForm() {
  const form = useForm({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });

  const onSubmit = (data: z.infer<typeof schema>) => {
    // 送信処理
  };

  return (
    <Form {...form}>
      <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
        <FormField
          control={form.control}
          name="email"
          render={({ field }) => (
            <FormItem>
              <FormLabel>メールアドレス</FormLabel>
              <FormControl>
                <Input placeholder="mail@example.com" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />
        <Button type="submit">ログイン</Button>
      </form>
    </Form>
  );
}
```

## 7. 重要な制約事項

### 重要度: 最高

1. UI 変更の制限

-**既存の UI コンポーネントやレイアウトの変更は禁止**

-**変更が必要な場合は必ず事前承認を得ること**

- レイアウト、色、フォント、間隔などの変更は特に注意

2. コンポーネントの追加

- 新規コンポーネントは既存の設計原則に従う
- 既存のコンポーネントの再利用を優先

## 8. フィードバックとローディング

### 重要度: 高

### ローディング状態

```typescript
// Next.js loading.tsx
import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="space-y-4 p-6">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

// コンポーネント内
{isLoading ? (
  <div className="flex flex-1 items-center justify-center">
    <Loader2 className="h-6 w-6 animate-spin" />
  </div>
) : (
  <Content />
)}
```

### トースト通知

```typescript
import { toast } from "sonner";

// 成功
toast.success("保存しました");

// エラー
toast.error("保存に失敗しました");
```

## 9. アイコンと画像

### 重要度: 中

### アイコン

```typescript
// 良い例：lucide-react
import { Home, User, Settings } from "lucide-react";

<Home className="h-5 w-5 text-primary" />
```

### 画像最適化

```typescript
// 良い例：next/image
import Image from "next/image";

<Image
  src={imageUrl}
  alt="説明"
  width={100}
  height={100}
  className="rounded-lg object-cover"
/>
```

## 10. ダークモード対応

### 重要度: 高

```typescript
// Tailwind CSS のダークモード
<div className="bg-white dark:bg-gray-900">
  <p className="text-gray-900 dark:text-white">テキスト</p>
</div>

// next-themes を使用
import { useTheme } from "next-themes";

const { theme, setTheme } = useTheme();
```

## 11. コンポーネント設計原則

### 重要度: 高

- 単一責任の原則
- Props 経由での柔軟なカスタマイズ
- 適切なコンポーネント分割

```typescript
// 良い例
interface CardProps {
  title: string;
  children: React.ReactNode;
  className?: string;
  onClick?: () => void;
}

export function Card({ title, children, className, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={cn("rounded-lg bg-white p-4 shadow-sm", className)}
    >
      <h3 className="mb-2 text-lg font-bold">{title}</h3>
      {children}
    </div>
  );
}

// 悪い例
interface CardProps {
  title: string;
  titleColor: string; // 不要なカスタマイズ
  customPadding: number; // 避けるべき
}
```

## 注意事項

1. デザインの一貫性

- Tailwind CSS クラスの一貫した使用
- カスタムスタイルの最小化
- デザイントークン（CSS Variables）の遵守

2. パフォーマンス

- 不要な再レンダリングの防止（memo, useMemo, useCallback）
- 画像の最適化（next/image）
- Server Components の活用

3. テスト

- コンポーネントの Testing Library テスト
- 複数ブラウザでの表示確認
- レスポンシブ表示の確認

4. ドキュメント

- コンポーネントの使用例
- Props の型定義

これらのルールは、プロジェクトの一貫性と保守性を確保するために重要です。

変更が必要な場合は、必ずチームでの承認プロセスを経てください。
