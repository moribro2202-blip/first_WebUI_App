---
name: revenuecat-setup
description: RevenueCatとApp Store Connectのアプリ内課金設定ガイド。商品作成、Offering設定、Shared Secret設定など、ステップバイステップで説明。課金実装、IAP、In-App Purchase時に使用。
---

# RevenueCat + App Store Connect 設定ガイド

アプリ内課金（In-App Purchase）をRevenueCatで実装するための完全ガイド。

## When to Use This Skill

- アプリ内課金を新規実装する時
- RevenueCatの設定方法がわからない時
- 「商品を取得できませんでした」エラーが出た時
- 「Could not check」エラーの対処時
- App Store Connectで商品を作成する時

---

## 前提条件

- [ ] Apple Developer Program に登録済み
- [ ] App Store Connect で有料Appの契約が完了している
- [ ] RevenueCat アカウントを作成済み

---

## Step 1: App Store Connect - 商品作成

1. **App Store Connect** (https://appstoreconnect.apple.com) にログイン
2. アプリを選択 → 左メニュー「**収益化**」→「**アプリ内課金**」
3. 「**+**」ボタンで新規作成
4. 以下を入力:
   - **種類**: 消耗型 / 非消耗型 / サブスクリプション
   - **参照名**: 商品の管理用名前（例: 30回パック）
   - **製品ID**: コードで使用するID（例: `credits_30`）
     - ⚠️ 一度設定すると変更不可
     - ⚠️ 削除した製品IDは再利用不可
5. 商品詳細を設定:
   - **価格**: 価格スケジュールで設定
   - **App Store情報**: 表示名と説明（ローカライズ）
   - **審査に関する情報**: スクリーンショット（**必須**）
6. ステータスが「**提出準備完了**」になることを確認

### よくある問題

| 問題 | 原因 | 対策 |
|------|------|------|
| ステータスが「メタデータが不足」 | 審査用スクリーンショットがない | 購入画面のスクリーンショットをアップロード |
| ステータスが「下書き」のまま | 必須項目が未入力 | 価格、表示名、説明、スクリーンショットを確認 |

---

## Step 2: App Store Connect - 共有シークレット取得

1. App Store Connect → アプリ → 「**一般**」→「**アプリ情報**」
2. 下にスクロールして「**App用共有シークレット**」
3. 「**管理**」→「**生成**」
4. 32文字のシークレットを**コピーして保存**

⚠️ このシークレットはRevenueCatに設定する（Step 4で使用）

---

## Step 3: RevenueCat - プロジェクト設定

1. **RevenueCat** (https://app.revenuecat.com) にログイン
2. 「**+ New Project**」でプロジェクト作成
3. 左メニュー「**Apps & providers**」→「**+ Add app config**」
4. **App Store App** を選択:
   - **App name**: アプリ名
   - **App Bundle ID**: アプリのBundle ID（App Store Connectと一致必須）

---

## Step 4: RevenueCat - Shared Secret設定

⭐ **重要**: この設定がないと「Could not check」エラーになる

1. **Apps & providers** → 作成したアプリをクリック
2. 下にスクロールして「**App-specific shared secret (Legacy)**」を展開
3. App Store Connectで取得したシークレットを入力
4. 「**Set secret**」をクリック
5. RevenueCatアカウントのパスワードを入力して確認

---

## Step 5: RevenueCat - 商品登録

1. 左メニュー「**Product catalog**」→「**Products**」
2. 作成したアプリの「**+ New**」をクリック
3. 以下を入力:
   - **Identifier**: App Store Connectの製品IDと**完全に一致**
     - 例: `credits_30`（大文字小文字も一致）
   - **Display Name**: 表示名

### 確認ポイント

- Statusが「**Could not check**」の場合:
  - Shared Secretが設定されているか確認
  - 製品IDが完全に一致しているか確認
  - App Store Connectの商品が「提出準備完了」か確認

---

## Step 6: RevenueCat - Entitlements作成

1. 「**Product catalog**」→「**Entitlements**」→「**+ New**」
2. 以下を入力:
   - **Identifier**: 権限のID（例: `premium`, `credits`）
   - **Description**: 説明
3. 作成後、Entitlementをクリック
4. 「**Attach**」で商品を紐付け

---

## Step 7: RevenueCat - Offering作成

⭐ **重要**: この設定がないと商品が取得できない

### 7-1. Offering作成

1. 「**Product catalog**」→「**Offerings**」→「**+ New offering**」
2. 以下を入力:
   - **Identifier**: `default`（推奨）
   - **Display Name**: 表示名

### 7-2. Package追加

1. 作成したOfferingをクリック → 「**Edit**」
2. 「**+ New Package**」でパッケージ追加
3. 以下を入力:
   - **Identifier**: 「**Custom**」を選択 → カスタムID入力（例: `credits_30_pack`）
   - **Description**: 説明（例: 30回パック）
   - **Products**: 「Receipt Memo」横の「No product」→ 商品を選択
4. 「**Save**」
5. すべての商品についてPackageを追加

### 7-3. Current設定確認

Offerings一覧で、作成したOfferingの横に**青いチェックマーク ✓**があることを確認

- ✓がある = Current設定済み（アプリから取得可能）
- ✓がない = Actionsメニューから「**Make Current**」を選択

---

## Step 8: アプリ側の設定

### 環境変数 (.env)

```
EXPO_PUBLIC_REVENUECAT_API_KEY=appl_xxxxxxxxxxxxxxxx
```

APIキーの取得場所: RevenueCat → **API keys** → **Public API key**

### 商品IDの定義 (lib/purchases.ts)

```typescript
export const PRODUCT_CREDITS: { [key: string]: number } = {
  credits_30: 30,    // App Store Connectの製品IDと一致
  credits_100: 100,
};
```

### 初期化コード

```typescript
import Purchases from "react-native-purchases";

Purchases.configure({
  apiKey: process.env.EXPO_PUBLIC_REVENUECAT_API_KEY,
});
```

### 商品取得コード

```typescript
const offerings = await Purchases.getOfferings();
if (offerings.current?.availablePackages) {
  // 商品が取得できた
  const packages = offerings.current.availablePackages;
}
```

---

## トラブルシューティング

### 「商品を取得できませんでした」

| 確認項目 | 対策 |
|----------|------|
| Offeringが作成されているか | Product catalog → Offerings を確認 |
| OfferingがCurrentか | 青いチェックマーク ✓ があるか確認 |
| PackagesにProductsがあるか | Offering内のPackagesを確認 |
| APIキーは正しいか | Public API keyを使用しているか確認 |

### 「Could not check」が消えない

| 確認項目 | 対策 |
|----------|------|
| Shared Secretは設定済みか | Apps & providers → アプリ → App-specific shared secret |
| 商品IDは一致しているか | 大文字小文字、スペースも完全一致か確認 |
| App Store Connectの商品ステータス | 「提出準備完了」になっているか確認 |

### TestFlightで動作しない

| 確認項目 | 対策 |
|----------|------|
| 新しいビルドをアップロードしたか | EAS Buildで再ビルド |
| Sandboxテスターでテストしているか | 本番購入はできない |

---

## チェックリスト

### App Store Connect
- [ ] 商品を作成した
- [ ] 種類（消耗型など）を選択した
- [ ] 製品ID（identifier）を設定した
- [ ] 価格を設定した
- [ ] 表示名・説明を入力した
- [ ] 審査用スクリーンショットをアップロードした
- [ ] ステータスが「提出準備完了」になった
- [ ] 共有シークレットを生成した

### RevenueCat
- [ ] プロジェクトを作成した
- [ ] アプリを追加した（Bundle ID一致）
- [ ] Shared Secretを設定した
- [ ] Productsを追加した（ID完全一致）
- [ ] Entitlementsを作成した
- [ ] EntitlementsにProductsを紐付けた
- [ ] Offeringを作成した
- [ ] PackagesにProductsを紐付けた
- [ ] OfferingがCurrentに設定されている（青い✓）

### アプリ
- [ ] APIキーを環境変数に設定した
- [ ] 商品IDをコードに定義した
- [ ] 購入処理を実装した
- [ ] 購入復元機能を実装した

---

## AI Assistant Instructions

アプリ内課金の実装を行う時:

1. このガイドのチェックリストに沿って設定を確認
2. 「Could not check」エラーはShared Secret設定を最初に確認
3. 「商品を取得できませんでした」はOffering設定を確認
4. 設定完了後、TestFlightでSandboxテストを実施
5. 本番リリース前にモックデータのフォールバックを削除

### 参考リンク

- [RevenueCat Docs](https://docs.revenuecat.com/)
- [App Store Connect Help](https://help.apple.com/app-store-connect/)
- [StoreKit Documentation](https://developer.apple.com/documentation/storekit)
