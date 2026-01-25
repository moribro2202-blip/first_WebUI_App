# トラブルシューティング

## 開発サーバー関連

### Metro Bundler が起動しない

```powershell
npx expo start --clear
```

### "Unable to resolve module" エラー


```powershell
Remove-Item -Recurse -Force node_modules
npm install
npx expo start --clear
```

## Android 関連

### エミュレータが起動しない

1. Android Studio > Virtual Device Manager
2. 新しいエミュレータを作成
3. API Level 24 以上を選択

### "INSTALL_FAILED_INSUFFICIENT_STORAGE"

1. Android Studio > Virtual Device Manager
2. 該当デバイスの編集
3. Show Advanced Settings > Internal Storage を増加

### ADB 接続エラー

```powershell
adb kill-server
adb start-server
```

## Firebase 関連

### "Firebase App not initialized" エラー

1. `lib/firebase.ts` の設定を確認
2. 環境変数を確認:
   ```powershell
   echo $env:EXPO_PUBLIC_FIREBASE_API_KEY
   ```

### Authentication エラー

1. Firebase Console で認証プロバイダが有効か確認
2. `google-services.json` が正しいか確認

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

## ビルド関連

### EAS Build 失敗

```powershell
npx expo doctor
npx expo install --check
```

### "SDK version mismatch" エラー

```powershell
npx expo install expo@latest
npx expo install --fix
```

### ビルドしてもTestFlightに載らない

**原因**: `eas build` はビルド作成のみ。TestFlightへのアップロードは別コマンド。

**解決**:
```powershell
# ビルド後にサブミット
eas submit --platform ios --latest

# または、1コマンドで両方実行
eas build --platform ios --profile production --auto-submit
```

### "Missing submit profile" エラー

**原因**: `eas.json` に `submit` セクションがない

**解決**: `eas.json` に追加:
```json
{
  "build": { ... },
  "submit": {
    "production": {
      "ios": {
        "ascAppId": "YOUR_APP_ID"
      }
    }
  }
}
```

`ascAppId` は App Store Connect のアプリIDを入力。

---

## RevenueCat / アプリ内課金

### 「商品を取得できませんでした」

**確認項目**:
1. RevenueCat で Offering が作成されているか
2. Offering が「Current」に設定されているか（青い✓マーク）
3. Offering 内に Packages が追加されているか
4. 環境変数 `EXPO_PUBLIC_REVENUECAT_API_KEY` が正しいか

**解決**: RevenueCat ダッシュボードで Offerings 設定を確認

### 「Could not check」エラー（RevenueCat Products）

**原因**: RevenueCat が App Store Connect の商品を検証できない

**確認項目**:
1. Shared Secret が設定されているか
   - RevenueCat → Apps & providers → アプリ → App-specific shared secret (Legacy)
2. 商品IDが完全に一致しているか（大文字小文字も）
3. App Store Connect の商品が「提出準備完了」か

### Offering / Package 設定漏れ

**必要な設定**:
1. Products を追加（商品IDは App Store Connect と一致）
2. Entitlements を作成し、Products を紐付け
3. Offering を作成
4. Offering 内に Packages を追加し、Products を選択
5. Offering を「Make Current」に設定

詳細は `/revenuecat-setup` スキルを参照。

---

## App Store Connect

### 商品ステータスが「提出準備完了」にならない

**原因**: 必須項目が未入力

**必須項目**:
- [ ] 価格設定
- [ ] 表示名（ローカライズ）
- [ ] 説明（ローカライズ）
- [ ] 審査用スクリーンショット（**よく忘れる**）

### 共有シークレット（Shared Secret）の取得

1. App Store Connect → アプリ → 一般 → アプリ情報
2. 下にスクロール →「App用共有シークレット」→「管理」
3. 「生成」をクリック
4. 32文字のシークレットをコピー
5. RevenueCat に設定

## パフォーマンス関連

### アプリが遅い・カクつく

1. 開発モードでは遅い（正常）
2. リリースビルドでテスト:
   ```powershell
   npx expo start --no-dev
   ```

### メモリリーク

1. useEffect のクリーンアップを確認
2. リスナーの解除を確認
3. React DevTools でコンポーネントを確認

## 型エラー関連

### TypeScript エラーが大量に出る

```powershell
npx tsc --noEmit
Remove-Item -Recurse -Force node_modules\.cache
npm install
```

### NativeWind の className が認識されない

`tsconfig.json` を確認:

```json
{
  "compilerOptions": {
    "types": ["nativewind/types"]
  }
}
```

## リセット手順（最終手段）

```powershell
Remove-Item -Recurse -Force node_modules, .expo, android\.gradle, android\app\build -ErrorAction SilentlyContinue
npm install
npx expo start --clear
```

## 問題が解決しない場合

1. エラーメッセージで検索
2. [Expo GitHub Issues](https://github.com/expo/expo/issues)
3. [Expo Discord](https://chat.expo.dev/)
4. [Stack Overflow](https://stackoverflow.com/questions/tagged/expo)

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
