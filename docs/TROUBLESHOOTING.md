# トラブルシューティング

## 開発サーバー関連

### 開発サーバーが起動しない

```bash
# キャッシュクリアして再起動
rm -rf .next
npm run dev
```

### "Module not found" エラー

```bash
rm -rf node_modules
npm install
```

### ポートが使用中

```bash
# 別ポートで起動
npm run dev -- --port 3001

# または使用中のプロセスを確認して終了
npx kill-port 3000
```

## ビルド関連

### ビルドエラー

```bash
# 型チェック
npx tsc --noEmit

# キャッシュクリアしてビルド
rm -rf .next
npm run build
```

### "window is not defined" エラー

**原因**: Server Component で `window` や `document` にアクセスしている

**解決**:
1. `"use client"` ディレクティブを追加
2. または `typeof window !== "undefined"` でガード
3. または `useEffect` 内でアクセス

```typescript
"use client";

import { useEffect, useState } from "react";

export function WindowSize() {
  const [width, setWidth] = useState(0);

  useEffect(() => {
    setWidth(window.innerWidth);
  }, []);

  return <p>Width: {width}</p>;
}
```

### Hydration エラー

**原因**: サーバーとクライアントのレンダリング結果が異なる

**解決**:
1. 日付やランダム値を `useEffect` で設定
2. `suppressHydrationWarning` を使用（最終手段）
3. `dynamic(() => import(...), { ssr: false })` でクライアントのみレンダリング

## Firebase 関連

### "Firebase App not initialized" エラー

1. `lib/firebase.ts` の設定を確認
2. 環境変数を確認:
   ```bash
   echo $NEXT_PUBLIC_FIREBASE_API_KEY
   ```

### Authentication エラー

1. Firebase Console で認証プロバイダが有効か確認
2. 認証ドメインが正しく設定されているか確認

### Firestore 権限エラー

Firebase Console でセキュリティルールを確認:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if request.auth != null;
    }
  }
}
```

## Tailwind CSS 関連

### スタイルが適用されない

1. `tailwind.config.ts` の `content` パスを確認:
```typescript
const config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
};
```

2. クラス名にタイポがないか確認
3. 開発サーバーを再起動

### ダークモード切り替えが動かない

1. `tailwind.config.ts` で `darkMode: "class"` を設定
2. `<html>` タグに `dark` クラスが適用されているか確認
3. `next-themes` の `ThemeProvider` を設定

## デプロイ関連

### Vercel デプロイ失敗

```bash
# ローカルでビルドテスト
npm run build

# 環境変数が設定されているか確認
vercel env ls
```

### 本番で API が動かない

1. 環境変数が Vercel に設定されているか確認
2. API Routes のパスが正しいか確認
3. Vercel のログを確認

## パフォーマンス関連

### ページ読み込みが遅い

1. `next/image` で画像を最適化
2. Server Components を活用
3. 動的インポートで分割
4. Lighthouse でスコアを確認:
   ```
   Chrome DevTools > Lighthouse > Generate report
   ```

### バンドルサイズが大きい

```bash
# バンドル分析
npm run build
npx @next/bundle-analyzer
```

## 型エラー関連

### TypeScript エラーが大量に出る

```bash
npx tsc --noEmit
rm -rf node_modules/.cache
npm install
```

## リセット手順（最終手段）

```bash
rm -rf node_modules .next
npm install
npm run dev
```

## 問題が解決しない場合

1. エラーメッセージで検索
2. [Next.js GitHub Issues](https://github.com/vercel/next.js/issues)
3. [Next.js Discord](https://nextjs.org/discord)
4. [Stack Overflow](https://stackoverflow.com/questions/tagged/next.js)

---

## 新しい問題を発見した時（PDCA）

問題に遭遇して解決したら、このドキュメントに追記してください。

### 追記テンプレート

```markdown
### [問題の簡潔な説明]

**症状**: [エラーメッセージや挙動]

**原因**: [なぜ起きたか]

**解決**:
1. [解決手順1]
2. [解決手順2]

**再発防止**: [設定変更やチェックリスト追加など]
```

### 追記の判断基準

- [ ] 30分以上ハマった問題
- [ ] 原因が分かりにくかった問題
- [ ] 他のプロジェクトでも起きそうな問題
- [ ] ドキュメントに書いてなかった問題

上記に1つでも該当したら追記する。
