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
