"use client";

import { useEffect, useState } from "react";
import { LayoutDashboard } from "lucide-react";
import { StatsCards } from "@/components/features/dashboard/stats-cards";
import { BetTypeStats } from "@/components/features/dashboard/bet-type-stats";
import { RecentPredictions } from "@/components/features/dashboard/recent-predictions";
import { M7DashboardStats } from "@/components/features/dashboard/m7-stats";
import { OpsChecklist } from "@/components/features/dashboard/ops-checklist";
import { getPredictions, getResults, getResultByPredictionId } from "@/lib/storage";
import { calcOverallStats, calcPerformanceStats } from "@/lib/calc-stats";
import type { Prediction, RaceResult } from "@/types";

export default function DashboardPage() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [results, setResults] = useState<RaceResult[]>([]);
  const [resultMap, setResultMap] = useState<Map<string, RaceResult>>(new Map());

  useEffect(() => {
    const preds = getPredictions();
    const res = getResults();
    setPredictions(preds);
    setResults(res);

    const map = new Map<string, RaceResult>();
    for (const p of preds) {
      const r = getResultByPredictionId(p.id);
      if (r) map.set(p.id, r);
    }
    setResultMap(map);
  }, []);

  const overall = calcOverallStats(results);
  const betStats = calcPerformanceStats(results);

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <LayoutDashboard className="h-6 w-6" />
        <h2 className="text-2xl font-bold">ダッシュボード</h2>
      </div>

      <OpsChecklist />
      <M7DashboardStats />
      <StatsCards stats={overall} />
      <BetTypeStats stats={betStats} />
      <RecentPredictions predictions={predictions} results={resultMap} />
    </div>
  );
}
