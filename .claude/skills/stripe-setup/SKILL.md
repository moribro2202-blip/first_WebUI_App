---
name: stripe-setup
description: StripeによるWeb決済設定ガイド。商品作成、Checkout Session設定、Webhook設定など、ステップバイステップで説明。決済実装、課金、サブスクリプション時に使用。
---

# Stripe 決済設定ガイド

Webアプリにおける決済機能をStripeで実装するための完全ガイド。

## When to Use This Skill

- Web決済を新規実装する時
- Stripeの設定方法がわからない時
- サブスクリプション機能を実装する時
- Checkout Session を作成する時

---

## 前提条件

- [ ] Stripe アカウントを作成済み
- [ ] Stripe ダッシュボードで API キーを取得済み
- [ ] Next.js プロジェクトがセットアップ済み

---

## Step 1: Stripe パッケージインストール

```bash
npm install stripe @stripe/stripe-js
```

---

## Step 2: 環境変数の設定

`.env.local` に以下を追加:

```
STRIPE_SECRET_KEY=sk_test_xxx
NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
```

---

## Step 3: Stripe 初期化

### サーバー側 (lib/stripe.ts)

```typescript
import Stripe from "stripe";

export const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!, {
  apiVersion: "2024-04-10",
});
```

### クライアント側 (lib/stripe-client.ts)

```typescript
import { loadStripe } from "@stripe/stripe-js";

export const stripePromise = loadStripe(
  process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!
);
```

---

## Step 4: Stripe ダッシュボードで商品作成

1. **Stripe Dashboard** → Products → + Add product
2. 以下を入力:
   - **Name**: 商品名
   - **Price**: 価格（一回払い or 定期）
3. Price ID をコピー（`price_xxx`）

---

## Step 5: Checkout Session API Route

```typescript
// app/api/checkout/route.ts
import { NextResponse } from "next/server";
import { stripe } from "@/lib/stripe";

export async function POST(request: Request) {
  const { priceId } = await request.json();

  const session = await stripe.checkout.sessions.create({
    mode: "subscription", // or "payment"
    payment_method_types: ["card"],
    line_items: [
      {
        price: priceId,
        quantity: 1,
      },
    ],
    success_url: `${process.env.NEXT_PUBLIC_APP_URL}/success?session_id={CHECKOUT_SESSION_ID}`,
    cancel_url: `${process.env.NEXT_PUBLIC_APP_URL}/pricing`,
  });

  return NextResponse.json({ url: session.url });
}
```

---

## Step 6: フロントエンドの購入ボタン

```typescript
"use client";

export function PurchaseButton({ priceId }: { priceId: string }) {
  const handleClick = async () => {
    const response = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ priceId }),
    });

    const { url } = await response.json();
    window.location.href = url;
  };

  return (
    <button onClick={handleClick}>
      購入する
    </button>
  );
}
```

---

## Step 7: Webhook 設定

### API Route

```typescript
// app/api/webhook/route.ts
import { NextResponse } from "next/server";
import { stripe } from "@/lib/stripe";
import { headers } from "next/headers";

export async function POST(request: Request) {
  const body = await request.text();
  const headersList = await headers();
  const signature = headersList.get("stripe-signature")!;

  let event;
  try {
    event = stripe.webhooks.constructEvent(
      body,
      signature,
      process.env.STRIPE_WEBHOOK_SECRET!
    );
  } catch (err) {
    return NextResponse.json({ error: "Webhook signature verification failed" }, { status: 400 });
  }

  switch (event.type) {
    case "checkout.session.completed":
      // 購入完了処理
      break;
    case "customer.subscription.updated":
      // サブスクリプション更新
      break;
    case "customer.subscription.deleted":
      // サブスクリプション解約
      break;
  }

  return NextResponse.json({ received: true });
}
```

### Stripe CLI でローカルテスト

```bash
# Stripe CLI インストール後
stripe listen --forward-to localhost:3000/api/webhook
```

---

## トラブルシューティング

### 「Webhook signature verification failed」

| 確認項目 | 対策 |
|----------|------|
| STRIPE_WEBHOOK_SECRET は正しいか | Stripe CLI の出力を確認 |
| request.text() を使っているか | JSON.parse せずに raw body を渡す |

### Checkout が開かない

| 確認項目 | 対策 |
|----------|------|
| API キーは正しいか | テストキーを使用しているか確認 |
| Price ID は正しいか | Stripe ダッシュボードで確認 |
| success_url/cancel_url は正しいか | 完全なURLか確認 |

---

## チェックリスト

### Stripe ダッシュボード
- [ ] 商品を作成した
- [ ] 価格を設定した
- [ ] Webhook エンドポイントを登録した（本番時）

### アプリ
- [ ] 環境変数を設定した
- [ ] Checkout Session API を作成した
- [ ] Webhook API を作成した
- [ ] 購入成功画面を作成した
- [ ] テスト購入が成功した

---

## AI Assistant Instructions

決済機能の実装を行う時:

1. このガイドのチェックリストに沿って設定を確認
2. テスト環境（sk_test_）で開発する
3. Stripe CLI でWebhookをローカルテストする
4. 本番公開前にテストモードからライブモードに切り替え

### 参考リンク

- [Stripe Docs](https://stripe.com/docs)
- [Stripe Next.js Example](https://github.com/vercel/next.js/tree/canary/examples/with-stripe-typescript)
