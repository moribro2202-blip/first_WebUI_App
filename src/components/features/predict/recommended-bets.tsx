"use client";

import { Star } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { BET_TYPE_LABELS } from "@/types";
import type { RecommendedBet } from "@/types";

type ExtendedBet = RecommendedBet & {
  allocation?: number;
};

function ConfidenceStars({ level }: { level: number }) {
  return (
    <div className="flex gap-0.5">
      {Array.from({ length: 5 }, (_, i) => (
        <Star
          key={i}
          className={`h-3.5 w-3.5 ${i < level ? "fill-yellow-400 text-yellow-400" : "text-muted"}`}
        />
      ))}
    </div>
  );
}

type Props = {
  bets: ExtendedBet[];
  budget?: number;
};

export function RecommendedBets({ bets, budget }: Props) {
  if (bets.length === 0) return null;

  const defaultTab = bets[0]?.betType ?? "tansho";

  // 券種ごとの合計allocation
  const totalAlloc = bets.reduce((sum, b) => sum + (b.allocation ?? 0), 0);

  return (
    <div className="space-y-3">
      {budget && budget > 0 && (
        <div className="rounded-md bg-muted p-3">
          <p className="text-sm font-medium">
            予算: {budget.toLocaleString()}円
          </p>
        </div>
      )}
      <Tabs defaultValue={defaultTab}>
        <TabsList className="flex-wrap">
          {bets.map((bet) => (
            <TabsTrigger key={bet.betType} value={bet.betType}>
              {BET_TYPE_LABELS[bet.betType]}
            </TabsTrigger>
          ))}
        </TabsList>
        {bets.map((bet) => {
          const betTotal =
            budget && bet.allocation && totalAlloc > 0
              ? Math.round((budget * bet.allocation) / totalAlloc / 100) * 100
              : null;

          const comboCount = bet.combinations.length;
          const perCombo =
            betTotal && comboCount > 0
              ? Math.max(100, Math.round(betTotal / comboCount / 100) * 100)
              : null;

          return (
            <TabsContent key={bet.betType} value={bet.betType}>
              <Card>
                <CardContent className="pt-4">
                  <div className="mb-3 flex flex-wrap items-center gap-3">
                    <span className="font-semibold">
                      {BET_TYPE_LABELS[bet.betType]}
                    </span>
                    <ConfidenceStars level={bet.confidence} />
                    {betTotal !== null && betTotal > 0 && (
                      <Badge variant="outline" className="text-xs">
                        合計 {betTotal.toLocaleString()}円
                      </Badge>
                    )}
                  </div>

                  {/* 各買い目と個別配分 */}
                  <div className="space-y-1.5">
                    {bet.combinations.map((combo, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between rounded-md border px-3 py-1.5"
                      >
                        <Badge variant="secondary" className="text-sm">
                          {combo}
                        </Badge>
                        {perCombo !== null && perCombo > 0 && (
                          <span className="text-sm font-medium">
                            {perCombo.toLocaleString()}円
                          </span>
                        )}
                      </div>
                    ))}
                  </div>

                  {betTotal !== null && betTotal > 0 && (
                    <div className="mt-3 rounded-md bg-primary/5 p-2 text-xs text-muted-foreground">
                      配分 {bet.allocation}% → 合計{" "}
                      {betTotal.toLocaleString()}円 ÷ {comboCount}点 ={" "}
                      各{perCombo?.toLocaleString()}円
                    </div>
                  )}
                </CardContent>
              </Card>
            </TabsContent>
          );
        })}
      </Tabs>
    </div>
  );
}
