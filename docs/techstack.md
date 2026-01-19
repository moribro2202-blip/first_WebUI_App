

# 技術スタック（React Native/Expo）

## フロントエンド

### コアテクノロジー

-**Expo** (SDK 52.x) - React Native 開発プラットフォーム

-**React Native** (v0.76.x) - クロスプラットフォームモバイルフレームワーク

-**React** (v18.3.x) - UI ライブラリ

-**TypeScript** (v5.x) - 型付き JavaScript

### ナビゲーション

-**Expo Router** (v4.x) - ファイルベースルーティング

- Stack, Tabs, Drawer ナビゲーション対応
- ディープリンク対応

### UI コンポーネント

-**NativeWind** (v4.x) - Tailwind CSS for React Native

- Tailwind の構文をそのまま使用可能

-**Gluestack UI** または **Tamagui** - UIコンポーネントライブラリ（オプション）

-**lucide-react-native** - アイコンライブラリ

-**React Native Reanimated** (v3.x) - アニメーションライブラリ

-**React Native Gesture Handler** - ジェスチャー操作

### 状態管理

-**Zustand** (v4.x) - 軽量状態管理

-**TanStack Query** (v5.x) - サーバー状態管理・キャッシュ

## バックエンド（Firebase）

| サービス                 | 用途                                   |

| ------------------------ | -------------------------------------- |

| Firebase Authentication  | ユーザー認証（メール、Apple、Google）  |

| Cloud Firestore          | ユーザーデータ、お気に入り、履歴の保存 |

| Firebase Storage         | ユーザーの写真保存                     |

| Firebase Cloud Messaging | プッシュ通知                           |

| Firebase Analytics       | 利用状況分析                           |

### Firebase SDK

-**firebase** (v10.x) - Firebase JavaScript SDK

-**@react-native-async-storage/async-storage** - 認証状態の永続化

## フォーム処理

-**React Hook Form** (v7.x) - フォーム状態管理

-**Zod** (v3.x) - スキーマバリデーション

## ユーティリティ

### 日付処理

-**date-fns** (v3.x) - 日付操作ライブラリ

### ストレージ

-**@react-native-async-storage/async-storage** - ローカルストレージ

-**expo-secure-store** - セキュアストレージ（認証トークン等）

### メディア

-**expo-image-picker** - 画像選択

-**expo-camera** - カメラ機能

-**expo-image** - 最適化された画像表示

### その他

-**expo-haptics** - 触覚フィードバック

-**expo-linking** - ディープリンク

-**expo-notifications** - プッシュ通知

-**expo-constants** - アプリ定数

## 認証関連

-**expo-auth-session** - OAuth認証フロー

-**expo-apple-authentication** - Apple サインイン

-**expo-crypto** - 暗号化ユーティリティ

## 開発ツール

-**ESLint** (v8.x) - コード品質管理

-**Prettier** (v3.x) - コードフォーマッター

-**TypeScript** - 型チェック

## テスト

-**Jest** - ユニットテスト

-**React Native Testing Library** - コンポーネントテスト

-**Detox** (オプション) - E2Eテスト

## ビルド・デプロイメント

### 開発

-**Expo Go** - 開発中のプレビュー

-**expo-dev-client** - カスタム開発クライアント

### 本番

-**EAS Build** - クラウドビルドサービス

-**EAS Submit** - App Store / Google Play 提出

-**EAS Update** - OTA（Over-The-Air）アップデート

## 対応プラットフォーム

-**iOS** 15.0+

-**Android** API 24+ (Android 7.0+)

## 特徴

- ファイルベースルーティング（Expo Router）
- クロスプラットフォーム対応（iOS/Android）
- OTAアップデート対応
- オフライン対応（Firestore永続化）
- 型安全性の確保
- アクセシビリティ対応

## プロジェクト構造

```

src/

├── app/                    # Expo Router ページ

│   ├── (tabs)/            # タブナビゲーション

│   ├── (auth)/            # 認証画面

│   └── _layout.tsx        # ルートレイアウト

├── components/            # 共通コンポーネント

│   ├── ui/               # 基本UIコンポーネント

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

2. NativeWind は Tailwind CSS の構文をそのまま使用できるため、Web開発者も学習コストが低い
3. Firebase の各サービスは Firebase Console で事前に有効化が必要
4. EAS Build/Submit は Expo アカウントが必要
