"use client";

import { TrendingUp, Target, DollarSign, BarChart3 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

type OverallStats = {
  totalPredictions: number;
  hitRate: number;
  recoveryRate: number;
  profit: number;
};

export function StatsCards({ stats }: { stats: OverallStats }) {
  const cards = [
    {
      label: "総予想数",
      value: `${stats.totalPredictions}`,
      icon: BarChart3,
    },
    {
      label: "的中率",
      value: `${stats.hitRate.toFixed(1)}%`,
      icon: Target,
    },
    {
      label: "回収率",
      value: `${stats.recoveryRate.toFixed(1)}%`,
      icon: TrendingUp,
    },
    {
      label: "通算収支",
      value: `${stats.profit >= 0 ? "+" : ""}${stats.profit.toLocaleString()}円`,
      icon: DollarSign,
      color: stats.profit >= 0 ? "text-green-600" : "text-destructive",
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {cards.map((card) => (
        <Card key={card.label}>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2 text-muted-foreground">
              <card.icon className="h-4 w-4" />
              <span className="text-xs">{card.label}</span>
            </div>
            <p className={`mt-1 text-2xl font-bold ${card.color ?? ""}`}>
              {card.value}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
