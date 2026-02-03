---
name: release-check
description: リリース前チェックスキル。ビルド確認、App Store審査チェック、変更履歴作成を一括実行。リリース準備、審査提出、ストア公開前に使用。
---

# リリース前チェックスキル

App Store / Google Play へのリリース前に必要なチェックを一括で実行します。

## When to Use This Skill

- アプリをリリースする前
- 「/release-check」と入力された時
- 「リリース準備して」と依頼された時
- App Store / Google Play に提出する前

## ワークフロー

```
┌──────────────────┐
│ 1. バージョン確認  │ app.json のバージョン確認・更新
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. 品質チェック   │ 型チェック・テスト・Lint
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 3. ビルドテスト   │ EAS Build でビルド確認
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 4. 審査チェック   │ App Store ガイドライン確認
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 5. 変更履歴作成   │ CHANGELOG 更新
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 6. リリースノート │ ストア用リリースノート作成
└──────────────────┘
```

## 引数

```
/release-check                    # フルチェック
/release-check --version 1.2.0    # バージョン指定
/release-check --skip-build       # ビルドスキップ
/release-check --ios-only         # iOSのみ
/release-check --android-only     # Androidのみ
```

| 引数 | 説明 |
|------|------|
| `--version <x.y.z>` | リリースバージョンを指定 |
| `--skip-build` | ビルドテストをスキップ |
| `--ios-only` | iOSのみチェック |
| `--android-only` | Androidのみチェック |
| `--quick` | 最小限のチェックのみ |

## AI Assistant Instructions

### フェーズ1: バージョン確認

```bash
# 現在のバージョン確認
cat app.json | grep -A5 '"version"'
```

バージョン更新が必要な場合:
```json
// app.json
{
  "expo": {
    "version": "1.2.0",           // ユーザー向けバージョン
    "ios": {
      "buildNumber": "42"         // iOS ビルド番号
    },
    "android": {
      "versionCode": 42           // Android バージョンコード
    }
  }
}
```

**セマンティックバージョニング:**
- `x.0.0` - メジャー（破壊的変更）
- `x.y.0` - マイナー（新機能追加）
- `x.y.z` - パッチ（バグ修正）

### フェーズ2: 品質チェック

```bash
# 型チェック
npx tsc --noEmit

# テスト
npm test

# Lint（設定があれば）
npm run lint
```

**チェックリスト:**
- [ ] 型エラーなし
- [ ] テスト全件パス
- [ ] Lintエラーなし
- [ ] console.log 残存なし
- [ ] 開発用コード削除済み

### フェーズ3: ビルドテスト

```bash
# iOS ビルド
eas build --platform ios --profile preview

# Android ビルド
eas build --platform android --profile preview
```

**確認事項:**
- [ ] ビルド成功
- [ ] アプリ起動確認
- [ ] 主要機能の動作確認
- [ ] クラッシュなし

### フェーズ4: App Store 審査チェック

`/appstore-review` スキルを参照して以下を確認:

**必須チェック項目:**

| カテゴリ | 確認事項 |
|----------|----------|
| **プライバシー** | プライバシーポリシーURL設定 |
| **権限** | 使用する権限の説明文 |
| **課金** | In-App Purchase の設定（該当時） |
| **コンテンツ** | 不適切コンテンツなし |
| **機能** | クラッシュ・バグなし |
| **UI** | Apple HIG 準拠 |

```bash
# app.json の権限説明確認
cat app.json | grep -A20 'infoPlist'
```

### フェーズ5: 変更履歴作成

`CHANGELOG.md` を更新:

```markdown
# Changelog

## [1.2.0] - 2024-01-20

### Added
- 新機能A を追加
- 新機能B を追加

### Changed
- 既存機能C を改善

### Fixed
- バグD を修正
- バグE を修正

### Security
- セキュリティ修正F
```

### フェーズ6: リリースノート作成

**日本語版（App Store / Google Play）:**

```
【新機能】
・〇〇機能を追加しました
・△△機能を追加しました

【改善】
・□□の動作を改善しました

【バグ修正】
・××の問題を修正しました
```

**英語版:**

```
What's New:
• Added XX feature
• Added YY feature

Improvements:
• Improved ZZ performance

Bug Fixes:
• Fixed issue with AA
```

## 完了時の出力

```
✅ リリースチェック完了！

📋 チェック結果
├─ バージョン: 1.2.0 (build 42)
├─ 型チェック: ✅ 通過
├─ テスト: ✅ 全件パス (45/45)
├─ Lint: ✅ エラーなし
├─ iOS ビルド: ✅ 成功
├─ Android ビルド: ✅ 成功
└─ 審査チェック: ✅ 問題なし

📝 作成ファイル
├─ CHANGELOG.md 更新済み
└─ release-notes-1.2.0.md 作成済み

🚀 次のステップ
1. 変更履歴とリリースノートを確認
2. eas submit でストアに提出
3. App Store Connect / Google Play Console で審査提出
```

## リリースコマンド

```bash
# iOS 提出
eas submit --platform ios

# Android 提出
eas submit --platform android

# 両方同時
eas submit --platform all
```

## チェックリストテンプレート

```markdown
## リリースチェックリスト v1.2.0

### コード品質
- [ ] 型チェック通過
- [ ] テスト全件パス
- [ ] Lintエラーなし
- [ ] console.log 削除
- [ ] 開発用コード削除

### ビルド
- [ ] iOS ビルド成功
- [ ] Android ビルド成功
- [ ] 実機動作確認

### App Store 審査
- [ ] プライバシーポリシー設定
- [ ] 権限説明文設定
- [ ] スクリーンショット最新化
- [ ] アプリ説明文更新

### ドキュメント
- [ ] CHANGELOG 更新
- [ ] リリースノート作成
- [ ] バージョン番号更新
```

## 関連スキル

- `/appstore-review`: App Store 審査対策詳細
- `/dev-flow`: 開発フロー
- `/pr-ready`: PR作成
