"use client";

import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Prediction, RaceResult } from "@/types";

type Props = {
  predictions: Prediction[];
  results: Map<string, RaceResult>;
};

export function RecentPredictions({ predictions, results }: Props) {
  const recent = predictions.slice(0, 5);

  if (recent.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">最近の予想</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            まだ予想がありません。
            <Link href="/predict" className="ml-1 text-primary underline">
              レース予想を始める
            </Link>
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-base">最近の予想</CardTitle>
        <Link href="/history" className="text-sm text-primary hover:underline">
          すべて見る
        </Link>
      </CardHeader>
      <CardContent className="space-y-2">
        {recent.map((pred) => {
          const result = results.get(pred.id);
          return (
            <div
              key={pred.id}
              className="flex items-center justify-between rounded-md border px-3 py-2"
            >
              <div>
                <span className="text-xs text-muted-foreground">{pred.raceDate}</span>
                <p className="text-sm font-medium">{pred.raceName}</p>
              </div>
              {result ? (
                <Badge variant={result.profit >= 0 ? "default" : "secondary"}>
                  {result.profit >= 0 ? "+" : ""}{result.profit.toLocaleString()}円
                </Badge>
              ) : (
                <Badge variant="outline">未確定</Badge>
              )}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}
