---
name: release
description: リリース統合スキル。ビルド確認、App Store審査チェック、変更履歴作成を一括実行。リリース準備、審査提出、ストア公開、リジェクト対策、App Store審査時に使用。
---

# リリース統合スキル

App Store / Google Play へのリリース前に必要なチェックを一括で実行します。

> **Note**: 旧 `/release-check` と `/appstore-review` スキルは本スキルに統合されました。`/release --review-only` で審査対策のみを実行できます。

## When to Use This Skill

- アプリをリリースする前
- 「/release」と入力された時
- 「リリース準備して」と依頼された時
- App Store / Google Play に提出する前
- 審査でリジェクトされた時（--review-only）
- 審査ガイドラインを確認したい時（--review-only）

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
└────────┬─────────┘  ※ --skip-build でスキップ
         ▼
┌──────────────────┐
│ 4. 審査チェック   │ App Store ガイドライン確認（詳細）
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

| 引数 | 説明 |
|------|------|
| `--version <x.y.z>` | リリースバージョンを指定 |
| `--skip-build` | ビルドテストをスキップ |
| `--ios-only` | iOSのみチェック |
| `--android-only` | Androidのみチェック |
| `--quick` | 最小限のチェックのみ |
| `--review-only` | 審査チェックのみ（旧 appstore-review 相当） |

## 使用例

```bash
# フルチェック
/release

# バージョン指定
/release --version 1.2.0

# ビルドスキップ
/release --skip-build

# 審査チェックのみ（旧 /appstore-review 相当）
/release --review-only

# iOSのみ
/release --ios-only
```

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

### フェーズ3: ビルドテスト（--skip-build でスキップ）

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

#### 提出前チェックリスト（必須項目）

| 項目 | 確認内容 |
|------|----------|
| プライバシーポリシーURL | 設定済みか |
| サポートURL | 設定済みか |
| アプリアイコン | 1024x1024 |
| スクリーンショット | 各デバイスサイズ |
| アプリ説明文 | 記入済みか |
| 年齢制限 | 設定済みか |
| カテゴリ | 選択済みか |

#### 技術要件

- [ ] クラッシュしない
- [ ] すべての機能が動作する
- [ ] ログイン機能がある場合、テストアカウントを用意
- [ ] 最新のiOSバージョンで動作確認
- [ ] iPadでも正常に表示（Universal対応の場合）

#### よくあるリジェクト理由と対策

| Guideline | 原因 | 対策 |
|-----------|------|------|
| **2.1** アプリが完成していない | プレースホルダー、未実装機能 | すべての画面実装、TODO削除 |
| **2.3** 正確なメタデータ | スクリーンショットが実際と異なる | 最新版スクリーンショット使用 |
| **4.2** 最小限の機能 | 機能が少なすぎる | ネイティブ機能活用 |
| **5.1.1** データ収集 | プライバシーポリシーがない | プライバシーポリシー設定 |
| **3.1.1** アプリ内課金 | Apple以外の決済 | アプリ内課金を使用 |
| **4.0** デザイン | UIが雑、使いにくい | HIG準拠 |

#### ログイン機能がある場合（必須）

1. **Apple でサインイン**を実装（サードパーティログインがある場合は必須）
2. **テストアカウント**を審査時に提供
3. **アカウント削除機能**を実装

#### スクリーンショット要件

| デバイス | サイズ |
|----------|--------|
| iPhone 6.7" | 1290 x 2796 |
| iPhone 6.5" | 1284 x 2778 |
| iPhone 5.5" | 1242 x 2208 |
| iPad 12.9" | 2048 x 2732 |

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

## リジェクト時の対応（--review-only）

### 1. リジェクト理由を確認

App Store Connect > 解決センター

### 2. 対応方針

| 状況 | 対応 |
|------|------|
| 明確な修正点がある | 修正して再提出 |
| 理由に納得できない | 異議申し立て（Appeal） |
| 不明点がある | 解決センターで質問 |

### 3. 再提出時の注意

- 修正内容を審査メモに記載
- 該当箇所のスクリーンショットを添付
- 丁寧な説明を心がける

## ビルド → TestFlight → 審査提出 フロー

```bash
# Step 1: ビルド作成
eas build --platform ios --profile production

# Step 2: TestFlightにアップロード
eas submit --platform ios --latest

# ワンコマンドで実行（推奨）
eas build --platform ios --profile production --auto-submit
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
- [ ] Apple サインイン実装（該当時）
- [ ] アカウント削除機能実装
- [ ] テストアカウント用意

### ドキュメント
- [ ] CHANGELOG 更新
- [ ] リリースノート作成
- [ ] バージョン番号更新
```

## 参考リンク

- [App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/)
- [Human Interface Guidelines](https://developer.apple.com/design/human-interface-guidelines/)

## 関連スキル

- `/dev-flow`: 開発フロー
- `/revenuecat-setup`: In-App Purchase 設定
- `/hotfix`: 緊急修正フロー
