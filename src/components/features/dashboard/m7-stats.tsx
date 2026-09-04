"use client";

import { useEffect, useState } from "react";
import { Target, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type M7Stats = {
  total: {
    total_bets: number;
    total_invested: number;
    total_payout: number;
    hits: number;
    misses: number;
    pending: number;
  };
  byMonth: Array<{
    month: string;
    invested: number;
    payout: number;
    hits: number;
    count: number;
  }>;
  recent: Array<{
    id: number;
    race_id: string;
    race_date: string;
    combination: string;
    amount: number;
    odds: number | null;
    result: string;
    payout: number | null;
    ai_score_json: string | null;
  }>;
  recoveryRate: number;
};

export function M7DashboardStats() {
  const [stats, setStats] = useState<M7Stats | null>(null);

  useEffect(() => {
    fetch("/api/jrdb/paper-trade")
      .then(res => res.json())
      .then(data => setStats(data))
      .catch(() => {});
  }, []);

  if (!stats || stats.total.total_bets === 0) return null;

  const t = stats.total;
  const settled = (t.hits ?? 0) + (t.misses ?? 0);
  const invested = t.total_invested ?? 0;
  const payout = t.total_payout ?? 0;
  const rr = invested > 0 ? (payout / invested * 100) : 0;
  const pnl = payout - invested;
  const hitRate = settled > 0 ? (t.hits / settled * 100) : 0;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4" />
          <CardTitle className="text-sm">M7 ペーパートレード</CardTitle>
          <Badge variant="outline" className="text-[10px]">v25</Badge>
        </div>
      </CardHeader>
      <CardContent>
        {/* Summary row */}
        <div className="grid grid-cols-5 gap-2 text-center mb-4">
          <div>
            <div className="text-lg font-bold">{settled}</div>
            <div className="text-[10px] text-muted-foreground">決済済</div>
          </div>
          <div>
            <div className="text-lg font-bold text-green-600">{t.hits ?? 0}</div>
            <div className="text-[10px] text-muted-foreground">的中</div>
          </div>
          <div>
            <div className="text-lg font-bold">{hitRate.toFixed(1)}%</div>
            <div className="text-[10px] text-muted-foreground">的中率</div>
          </div>
          <div>
            <div className={cn("text-lg font-bold", rr >= 100 ? "text-green-600" : "text-red-500")}>
              {rr > 0 ? `${rr.toFixed(0)}%` : "-"}
            </div>
            <div className="text-[10px] text-muted-foreground">回収率</div>
          </div>
          <div>
            <div className={cn("text-lg font-bold", pnl >= 0 ? "text-green-600" : "text-red-500")}>
              {pnl >= 0 ? "+" : ""}{(pnl / 10000).toFixed(1)}万
            </div>
            <div className="text-[10px] text-muted-foreground">収支</div>
          </div>
        </div>

        {/* Pending */}
        {(t.pending ?? 0) > 0 && (
          <div className="mb-3 rounded bg-yellow-50 dark:bg-yellow-950 px-3 py-1.5 text-xs text-yellow-700 dark:text-yellow-300">
            未決済: {t.pending}件
          </div>
        )}

        {/* Monthly chart (simple bar) */}
        {stats.byMonth.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium text-muted-foreground mb-1">月別回収率</div>
            {stats.byMonth.slice(-6).map(m => {
              const mRR = m.invested > 0 ? (m.payout / m.invested * 100) : 0;
              const barWidth = Math.min(100, Math.max(5, mRR));
              return (
                <div key={m.month} className="flex items-center gap-2 text-[11px]">
                  <span className="w-14 text-right font-mono text-muted-foreground">{m.month}</span>
                  <div className="h-3 flex-1 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn("h-full rounded-full transition-all", mRR >= 100 ? "bg-green-500" : "bg-red-400")}
                      style={{ width: `${barWidth}%` }}
                    />
                  </div>
                  <span className={cn("w-12 text-right font-mono font-medium", mRR >= 100 ? "text-green-600" : "text-red-500")}>
                    {mRR.toFixed(0)}%
                  </span>
                </div>
              );
            })}
          </div>
        )}

        {/* Recent trades */}
        {stats.recent.length > 0 && (
          <div className="mt-3 pt-3 border-t">
            <div className="text-xs font-medium text-muted-foreground mb-1">直近の取引</div>
            <div className="space-y-0.5">
              {stats.recent.slice(0, 5).map(trade => (
                <div key={trade.id} className="flex items-center justify-between text-[11px]">
                  <span className="font-mono text-muted-foreground">{trade.race_date}</span>
                  <span className="font-mono">{trade.combination}</span>
                  {trade.result === "hit" && (
                    <span className="font-mono font-bold text-green-600">
                      +{((trade.payout ?? 0) - trade.amount).toLocaleString()}
                    </span>
                  )}
                  {trade.result === "miss" && (
                    <span className="font-mono text-red-500">-{trade.amount.toLocaleString()}</span>
                  )}
                  {trade.result === "pending" && (
                    <Badge variant="secondary" className="text-[9px] h-4">未決済</Badge>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
