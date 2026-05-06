---
name: debugging-guide
description: エラー発生時のトラブルシューティング手順。Web検索→GitHub Issues確認→依存関係チェック→最小構成テスト→コード修正の順で対応。
---

# デバッグ・トラブルシューティングガイド

エラー発生時の対応手順を定義します。コードの修正は最後の手段とし、まず既知の問題やパッケージ互換性を確認します。

## When to Use This Skill

- ランタイムエラーが発生した時
- ビルドエラーが発生した時
- 原因不明のエラーで困った時
- 「エラーを修正して」と依頼された時

## エラー対応フロー

```
エラー発生
    │
    ▼
Step 1: Web検索で既知の問題を確認
    │
    ▼
Step 2: GitHub Issuesを確認
    │
    ▼
Step 3: 依存関係の互換性チェック
    │
    ▼
Step 4: 最小構成でのテスト
    │
    ▼
Step 5: コードの修正（最後の手段）
```

## AI Assistant Instructions

### Step 1: Web検索で既知の問題を確認

エラーメッセージをそのままWeb検索する。パッケージ名とバージョンも含めて検索。

```
検索例:
- next.js 15 "Module not found" error
- tailwind css v4 "Cannot find module"
- firebase auth "popup blocked" next.js
```

**重要**: コードを修正する前に、必ずWeb検索を実行すること。

### Step 2: GitHub Issuesを確認

関連パッケージのGitHub Issuesを確認する：

| パッケージ | Issues URL |
|-----------|-----------|
| Next.js | https://github.com/vercel/next.js/issues |
| React | https://github.com/facebook/react/issues |
| Tailwind CSS | https://github.com/tailwindlabs/tailwindcss/issues |
| shadcn/ui | https://github.com/shadcn-ui/ui/issues |

### Step 3: 依存関係の互換性チェック

```bash
# バージョン確認
npm ls <package-name>

# 古いパッケージの確認
npm outdated

# 互換性の確認
npm audit
```

### Step 4: 最小構成でのテスト

問題を切り分けるため、段階的にテストする：

1. **最小限のコードで再現確認**
   ```tsx
   export default function TestPage() {
     return <div>Test</div>;
   }
   ```

2. **段階的にコンポーネントを追加**
   - レイアウト追加 → エラー発生？
   - 特定のコンポーネント追加 → エラー発生？

3. **原因コンポーネントを特定**

### Step 5: コードの修正（最後の手段）

上記で解決しない場合のみ、コードの修正を検討する。

## よくある原因パターン

| エラータイプ | よくある原因 | 対処法 |
|-------------|-------------|--------|
| Hydration Error | サーバーとクライアントのレンダリング不一致 | useEffect で動的値を設定、suppressHydrationWarning |
| Module not found | 依存関係の不足、パス間違い | `npm install` またはパス確認 |
| "window is not defined" | Server Component でブラウザAPIを使用 | "use client" を追加 |
| TypeError: Cannot read properties of null | 非同期データの未ロード | オプショナルチェーン（?.）を使用 |
| Build error | 型エラー、import エラー | `npx tsc --noEmit` で確認 |

## Next.js 特有の注意点

### 1. Server Components vs Client Components

- `"use client"` を忘れるとブラウザAPIが使えない
- Server Components では useState, useEffect が使えない
- クライアント専用のライブラリは dynamic import + `ssr: false` で対応

### 2. 環境変数

- クライアント側で使う環境変数には `NEXT_PUBLIC_` プレフィックスが必要
- `.env.local` はGitにコミットしない

### 3. キャッシュクリア

問題発生時はキャッシュクリアを試す：

```bash
# Next.js キャッシュ
rm -rf .next

# npm
rm -rf node_modules && npm install
```

## 実例: Hydration Error

### 症状
```
Hydration failed because the initial UI does not match what was rendered on the server.
```

### 原因
日付表示やランダム値など、サーバーとクライアントで異なる値をレンダリング

### 解決策
```typescript
"use client";

import { useEffect, useState } from "react";

export function CurrentDate() {
  const [date, setDate] = useState<string>("");

  useEffect(() => {
    setDate(new Date().toLocaleDateString("ja-JP"));
  }, []);

  return <span>{date}</span>;
}
```
