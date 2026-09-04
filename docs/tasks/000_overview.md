# タスク概要

## 機能一覧

| No | 機能名 | タスクファイル | ステータス | 依存 |
|----|--------|---------------|-----------|------|
| 1 | プロジェクト基盤・レイアウト | `001_foundation.md` | 🟢 完了 | - |
| 2 | レース情報入力画面 | `002_race_input.md` | 🟢 完了 | 1 |
| 3 | AI予想生成・表示 | `003_prediction.md` | 🟢 完了 | 2 |
| 4 | 結果入力・収支管理 | `004_result_input.md` | 🟢 完了 | 3 |
| 5 | ダッシュボード・成績分析 | `005_dashboard.md` | 🟢 完了 | 4 |
| 6 | 設定・仕上げ | `006_settings.md` | 🟢 完了 | 1 |

## ステータス凡例

- 🔴 未着手
- 🟡 進行中
- 🟢 完了

## 依存関係図

```
1. 基盤・レイアウト
├── 2. レース情報入力
│   └── 3. AI予想生成・表示
│       └── 4. 結果入力・収支管理
│           └── 5. ダッシュボード・成績分析
└── 6. 設定・仕上げ
```

## 実装済み（前回まで）

- [x] 型定義（`src/types/index.ts`）
- [x] AI予想API（`src/app/api/predict/route.ts`）
- [x] レースデータAPI（`src/app/api/races/route.ts`）- サンプルデータ
- [x] Firebase設定（`src/lib/firebase.ts`）
- [x] shadcn/ui コンポーネント（button, card, input, label, tabs, badge, table, select, textarea, separator, scroll-area, dialog）

## 参照

- [機能要件](../requirements/functional.md)
- [プロジェクト概要](../requirements/overview.md)
