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
- react-native-screens expo sdk 54 "expected dynamic type 'boolean'"
- expo "Module not found" react-navigation
- react-native 0.81 hermes TypeError
```

**重要**: コードを修正する前に、必ずWeb検索を実行すること。

### Step 2: GitHub Issuesを確認

関連パッケージのGitHub Issuesを確認する：

| パッケージ | Issues URL |
|-----------|-----------|
| Expo | https://github.com/expo/expo/issues |
| React Navigation | https://github.com/react-navigation/react-navigation/issues |
| React Native Screens | https://github.com/software-mansion/react-native-screens/issues |
| React Native | https://github.com/facebook/react-native/issues |

### Step 3: 依存関係の互換性チェック

```bash
# Expo プロジェクトの場合
npx expo-doctor

# 特定パッケージのバージョン確認
npm ls <package-name>

# 互換性のあるバージョンをインストール
npx expo install <package-name>
```

### Step 4: 最小構成でのテスト

問題を切り分けるため、段階的にテストする：

1. **最小限のコードで再現確認**
   ```tsx
   // 最小構成の例
   export default function App() {
     return (
       <View>
         <Text>Test</Text>
       </View>
     );
   }
   ```

2. **段階的にコンポーネントを追加**
   - ナビゲーション追加 → エラー発生？
   - 特定の画面追加 → エラー発生？
   - 特定のコンポーネント追加 → エラー発生？

3. **原因コンポーネントを特定**

### Step 5: コードの修正（最後の手段）

上記で解決しない場合のみ、コードの修正を検討する。

## よくある原因パターン

| エラータイプ | よくある原因 | 対処法 |
|-------------|-------------|--------|
| TypeError: expected dynamic type | パッケージバージョンの互換性問題 | パッケージのダウングレード |
| Module not found | 依存関係の不足、パス間違い | `npm install` または パス確認 |
| Native module error | New Architecture互換性 | 開発ビルドで確認 |
| Invariant Violation | コンポーネントの誤使用 | 公式ドキュメント確認 |

## Expo/React Native特有の注意点

### 1. Expo Goでは常にNew Architectureが有効

- `newArchEnabled: false` はExpo Goでは**無視される**
- New Architectureを無効にするには**開発ビルド**が必要

### 2. パッケージバージョンの互換性

- Expo SDKバージョンに合わせたパッケージを使用
- `npx expo install <package>` で互換バージョンをインストール
- 手動で `npm install` する場合はバージョンに注意

### 3. キャッシュクリア

問題発生時はキャッシュクリアを試す：

```bash
# Expo
npx expo start --clear

# Metro
npx react-native start --reset-cache

# npm
rm -rf node_modules && npm install
```

## 実例: react-native-screens 4.17.x問題

### 症状
```
TypeError: expected dynamic type 'boolean', but had type 'string'
```

### 原因
react-native-screens 4.17.x以降とExpo SDK 54の互換性問題

### 解決策
```bash
npm install react-native-screens@4.16.0
npx expo start --clear
```

### 参考
- https://github.com/software-mansion/react-native-screens/issues/3470
