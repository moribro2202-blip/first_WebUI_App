# 開発環境セットアップ

## 前提条件

- Windows 11
- Node.js 18.x 以上
- npm または yarn
- Git
- Android Studio + JDK 17

> **Note**: iOS ビルドは EAS Build（クラウド）を使用

## 初回セットアップ

### 1. リポジトリのクローン

```bash
git clone <repository-url>
cd <project-name>
```

### 2. 依存関係のインストール

```bash
npm install
```

### 3. 環境変数の設定

`.env.example` をコピーして `.env` を作成:

```powershell
copy .env.example .env
```

Firebase の設定値を入力:

```
EXPO_PUBLIC_FIREBASE_API_KEY=
EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN=
EXPO_PUBLIC_FIREBASE_PROJECT_ID=
EXPO_PUBLIC_FIREBASE_STORAGE_BUCKET=
EXPO_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=
EXPO_PUBLIC_FIREBASE_APP_ID=
```

### 4. 開発サーバーの起動

```bash
npx expo start
```

## 実機・エミュレータでの確認

### Expo Go（推奨）

1. スマホに Expo Go アプリをインストール
2. QR コードをスキャン

### Android エミュレータ

```bash
npx expo start --android
```

## よく使うコマンド

| コマンド | 説明 |
|----------|------|
| `npx expo start` | 開発サーバー起動 |
| `npx expo start --clear` | キャッシュクリアして起動 |
| `npx expo start --android` | Android エミュレータで起動 |
| `npm run lint` | ESLint 実行 |
| `npm run test` | テスト実行 |
| `npx tsc --noEmit` | 型チェック |
| `npx expo doctor` | プロジェクト健全性チェック |

## キャッシュクリア

```powershell
# Expo キャッシュクリア
npx expo start --clear

# node_modules 再インストール
Remove-Item -Recurse -Force node_modules
npm install
```

## 次のステップ

- `docs/requirements/functional.md` で実装する機能を確認
- `docs/techstack.md` で使用技術を確認
