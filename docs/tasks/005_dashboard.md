# Task 5: ダッシュボード・成績分析

## 概要

ホーム画面に成績サマリーを表示し、履歴画面で詳細な成績分析を行う。

## タスク

- [ ] ダッシュボード（`/` ホーム画面）
  - 通算成績カード（総予想数・的中率・回収率）
  - 馬券種別の回収率一覧
  - 最近の予想履歴（直近5件）
- [ ] 予想履歴画面（`/history`）
  - 予想一覧（日付・レース名・的中/不的中・収支）
  - 期間フィルター
  - 馬券種別フィルター
- [ ] 成績集計ロジック
  - 馬券種別の的中率・回収率
  - 期間別の成績
- [ ] 成績グラフ（recharts）
  - 回収率の推移グラフ

## 作成ファイル

```
src/
├── app/
│   ├── page.tsx                    （ダッシュボード実装）
│   └── history/page.tsx            （履歴画面実装）
├── components/features/dashboard/
│   ├── stats-cards.tsx             # 成績カード
│   ├── bet-type-stats.tsx          # 馬券種別成績
│   └── recent-predictions.tsx      # 最近の予想
├── components/features/history/
│   ├── prediction-list.tsx         # 予想履歴一覧
│   └── history-filters.tsx         # フィルター
└── lib/
    └── calc-stats.ts               # 成績集計ロジック
```

## 完了条件

- ダッシュボードに成績サマリーが表示される
- 履歴画面で予想の一覧・フィルタリングができる
