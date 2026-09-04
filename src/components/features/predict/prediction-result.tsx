"use client";

import { TrendingUp, AlertTriangle } from "lucide-react";
import { EV_CONFIG } from "@/lib/ev-engine";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { HorseRankingTable } from "./horse-ranking-table";
import { RecommendedBets } from "./recommended-bets";
import type { PredictionHorse, RecommendedBet } from "@/types";

type EvBet = {
  betType: string;
  combination: string;
  probability: number;
  odds: number;
  ev: number;
  kelly: number;
  warning?: string;
};

type Props = {
  horses: PredictionHorse[];
  recommendedBets: RecommendedBet[];
  analysis: string;
  budget?: number;
  evBets?: EvBet[];
  evLookup?: Record<string, number>;
  winProbabilities?: number[];
};

const BET_LABELS: Record<string, string> = {
  tansho: "単勝",
  fukusho: "複勝",
  umaren: "馬連",
  umatan: "馬単",
  wide: "ワイド",
  sanrenpuku: "三連複",
  sanrentan: "三連単",
};

export function PredictionResult({
  horses,
  recommendedBets,
  analysis,
  budget,
  evBets,
  evLookup,
  winProbabilities,
}: Props) {
  // EV105%以上の買い目（警告なし）
  const qualifiedEvBets =
    evBets?.filter((b) => b.ev >= 1.05) ?? [];
  // 警告付き（過信の疑い）
  const warningEvBets =
    evBets?.filter((b) => b.warning) ?? [];
  const hasEvBets = qualifiedEvBets.length > 0;

  // ケリー基準で予算配分（合計が予算を超えない）
  const totalKelly = qualifiedEvBets.reduce((s, b) => s + b.kelly, 0);
  const totalRawAmount = budget
    ? qualifiedEvBets.reduce((s, b) => s + budget * b.kelly, 0)
    : 0;
  const kellyScale =
    budget && totalRawAmount > budget ? budget / totalRawAmount : 1.0;

  return (
    <div className="space-y-6">
      {/* 分析コメント */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">AI分析</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm leading-relaxed">{analysis}</p>
        </CardContent>
      </Card>

      {/* AI偏差値ランキング */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">AI偏差値ランキング</CardTitle>
        </CardHeader>
        <CardContent>
          <HorseRankingTable
            horses={horses.map((h) => {
              // winProbabilitiesから勝率を取得（entries順のインデックス）
              const wpIdx = winProbabilities
                ? horses.indexOf(h)
                : -1;
              // horseNumberからwinProbabilitiesのインデックスを探す
              const wp = winProbabilities?.[h.horseNumber - 1];
              return { ...h, winProb: wp };
            })}
          />
        </CardContent>
      </Card>

      {/* EV計算による推奨買い目（105%以上のみ） */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <TrendingUp className="h-4 w-4" />
            数学的推奨買い目
            <Badge variant="outline" className="text-xs font-normal">
              予想回収率105%以上
            </Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {hasEvBets ? (
            <div className="space-y-2">
              {budget && budget > 0 && (
                <div className="rounded-md bg-muted p-2 text-sm">
                  予算: <span className="font-bold">{budget.toLocaleString()}円</span>
                </div>
              )}
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b bg-muted/50 text-xs">
                      <th className="p-2 text-left">券種</th>
                      <th className="p-2 text-left">買い目</th>
                      <th className="p-2 text-right">オッズ</th>
                      <th className="p-2 text-right">的中確率</th>
                      <th className="p-2 text-right">予想回収率</th>
                      {budget && budget > 0 && (
                        <th className="p-2 text-right">投資額</th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {qualifiedEvBets.map((bet, i) => {
                      const evPct = Math.round(bet.ev * 100);
                      // 修正4: ケリー配分（スケールアップしない）
                      const amount =
                        budget && bet.kelly > 0
                          ? Math.max(
                              100,
                              Math.round(
                                (budget * bet.kelly * kellyScale) / 100
                              ) * 100
                            )
                          : null;

                      return (
                        <tr key={i} className="border-b">
                          <td className="p-2">
                            <Badge variant="secondary" className="text-xs">
                              {BET_LABELS[bet.betType] ?? bet.betType}
                            </Badge>
                          </td>
                          <td className="p-2 font-mono font-bold">
                            {bet.combination}
                          </td>
                          <td className="p-2 text-right">
                            {bet.odds.toFixed(1)}倍
                          </td>
                          <td className="p-2 text-right">
                            {(bet.probability * 100).toFixed(1)}%
                          </td>
                          <td className="p-2 text-right">
                            <span
                              className={
                                evPct >= 120
                                  ? "font-bold text-red-500"
                                  : evPct >= 110
                                    ? "font-bold text-orange-500"
                                    : "font-bold text-green-600"
                              }
                            >
                              {evPct}%
                            </span>
                          </td>
                          {budget && budget > 0 && (
                            <td className="p-2 text-right font-bold">
                              {amount?.toLocaleString()}円
                            </td>
                          )}
                        </tr>
                      );
                    })}
                  </tbody>
                  {budget && budget > 0 && (
                    <tfoot>
                      <tr className="border-t bg-muted/30">
                        <td colSpan={5} className="p-2 text-right text-xs font-medium">
                          合計
                        </td>
                        <td className="p-2 text-right font-bold">
                          {qualifiedEvBets
                            .reduce((sum, bet) => {
                              const amt =
                                bet.kelly > 0
                                  ? Math.max(
                                      100,
                                      Math.round(
                                        (budget * bet.kelly * kellyScale) / 100
                                      ) * 100
                                    )
                                  : 0;
                              return sum + amt;
                            }, 0)
                            .toLocaleString()}
                          円
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
              <p className="text-xs text-muted-foreground">
                ※ 予想回収率 = 的中確率 × オッズ。105%以上 = 100円賭けて期待値105円以上。
                投資額はケリー基準（1/4）で算出。予算未達分は賭けません。
              </p>
              {warningEvBets.length > 0 && (
                <div className="mt-3 space-y-1 rounded-md border border-yellow-300 bg-yellow-50 p-3 dark:border-yellow-800 dark:bg-yellow-950/30">
                  <p className="text-xs font-medium text-yellow-700 dark:text-yellow-400">
                    ⚠ 過信の疑いがある買い目（EV {Math.round(EV_CONFIG.evCap * 100)}%超、除外済み）
                  </p>
                  {warningEvBets.map((bet, i) => (
                    <p key={i} className="text-xs text-yellow-600 dark:text-yellow-500">
                      {BET_LABELS[bet.betType] ?? bet.betType} {bet.combination}{" "}
                      EV={Math.round(bet.ev * 100)}% — {bet.warning}
                    </p>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-2 rounded-md bg-muted p-4 text-sm text-muted-foreground">
              <AlertTriangle className="h-4 w-4" />
              予想回収率105%以上の買い目が見つかりませんでした。このレースは見送りが推奨されます。
            </div>
          )}
        </CardContent>
      </Card>

      {/* AI推奨買い目（EV検証付き） */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base text-muted-foreground">
            AI推奨買い目（EV検証付き）
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {recommendedBets.map((bet, bi) => {
              return (
                <div key={bi} className="space-y-1">
                  <p className="text-sm font-semibold">
                    {BET_LABELS[bet.betType] ?? bet.betType}
                  </p>
                  <div className="space-y-1">
                    {bet.combinations.map((combo, ci) => {
                      // evLookupからこの買い目のEVを探す
                      const key = `${bet.betType}:${combo}`;
                      const ev = evLookup?.[key];
                      const isEvPlus = ev !== undefined && ev >= 1.05;
                      const isWarning = ev !== undefined && ev > 1.5;

                      return (
                        <div
                          key={ci}
                          className="flex items-center gap-2 rounded border px-3 py-1.5 text-sm"
                        >
                          <Badge variant="secondary">{combo}</Badge>
                          {ev !== undefined ? (
                            <Badge
                              variant={isWarning ? "outline" : isEvPlus ? "default" : "secondary"}
                              className={
                                isWarning
                                  ? "border-yellow-400 text-yellow-600"
                                  : isEvPlus
                                    ? "bg-green-600 text-white"
                                    : "bg-red-100 text-red-600"
                              }
                            >
                              EV {Math.round(ev * 100)}%
                              {isEvPlus && !isWarning ? " ✓" : ""}
                              {!isEvPlus ? " ✗" : ""}
                              {isWarning ? " ⚠" : ""}
                            </Badge>
                          ) : (
                            <span className="text-xs text-muted-foreground">
                              EV未計算
                            </span>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
