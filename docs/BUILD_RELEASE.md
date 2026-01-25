# ビルド・リリース手順

## 前提条件

- Expo アカウント（https://expo.dev）
- Apple Developer Program（iOS リリース用）
- Google Play Console アカウント（Android リリース用）

## EAS CLI セットアップ

### 1. EAS CLI インストール

```bash
npm install -g eas-cli
```

### 2. Expo ログイン

```bash
eas login
```

### 3. プロジェクト設定

```bash
eas build:configure
```

これで `eas.json` が生成される。

## eas.json 設定例

```json
{
  "cli": {
    "version": ">= 5.0.0"
  },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal"
    },
    "preview": {
      "distribution": "internal"
    },
    "production": {}
  },
  "submit": {
    "production": {}
  }
}
```

## ビルド

> **重要**: `eas build` はビルドを作成するだけです。
> TestFlight / Google Play にアップロードするには、別途 `eas submit` が必要です。
>
> **ビルド → TestFlight の流れ:**
> ```bash
> # 1. ビルド作成
> eas build --platform ios --profile production
>
> # 2. ビルド完了後、TestFlightにアップロード
> eas submit --platform ios --latest
> ```
>
> または、1コマンドで両方実行:
> ```bash
> eas build --platform ios --profile production --auto-submit
> ```

### 開発ビルド（内部テスト用）

```bash
# iOS
eas build --platform ios --profile development

# Android
eas build --platform android --profile development
```

### プレビュービルド（内部配布用）

```bash
# iOS
eas build --platform ios --profile preview

# Android
eas build --platform android --profile preview
```

### 本番ビルド（ストア提出用）

```bash
# iOS
eas build --platform ios --profile production

# Android
eas build --platform android --profile production

# 両方同時
eas build --platform all --profile production
```

## バージョン管理

`app.json` または `app.config.js` で管理:

```json
{
  "expo": {
    "version": "1.0.0",
    "ios": {
      "buildNumber": "1"
    },
    "android": {
      "versionCode": 1
    }
  }
}
```

### バージョン更新ルール

- `version`: ユーザーに見えるバージョン（1.0.0 → 1.1.0）
- `buildNumber` / `versionCode`: ストア提出ごとに +1

## ストア提出

### iOS (App Store)

```bash
eas submit --platform ios
```

初回は Apple Developer の設定が必要:
1. App Store Connect でアプリを作成
2. Bundle Identifier を設定
3. EAS で Apple 認証情報を設定

### Android (Google Play)

```bash
eas submit --platform android
```

初回は Google Play Console の設定が必要:
1. Google Play Console でアプリを作成
2. Package name を設定
3. サービスアカウントキーを EAS に設定

## OTA アップデート（EAS Update）

JavaScript のみの変更はストア審査なしで配信可能:

```bash
# プレビュー環境に配信
eas update --branch preview

# 本番環境に配信
eas update --branch production
```

## リリースチェックリスト

### ビルド前

- [ ] `app.json` のバージョン番号を更新
- [ ] 環境変数が本番用になっているか確認
- [ ] `npx tsc --noEmit` で型エラーがないか確認
- [ ] `npm run test` でテストが通るか確認
- [ ] `npx expo doctor` で問題がないか確認

### ビルド後

- [ ] 実機でテスト（iOS / Android 両方）
- [ ] 主要機能の動作確認
- [ ] Firebase 接続確認
- [ ] クラッシュがないか確認

### 提出前

- [ ] スクリーンショット準備
- [ ] アプリ説明文準備
- [ ] プライバシーポリシー URL
- [ ] サポート URL

## 参考リンク

- [EAS Build 公式ドキュメント](https://docs.expo.dev/build/introduction/)
- [EAS Submit 公式ドキュメント](https://docs.expo.dev/submit/introduction/)
- [EAS Update 公式ドキュメント](https://docs.expo.dev/eas-update/introduction/)
