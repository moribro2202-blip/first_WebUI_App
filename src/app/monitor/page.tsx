"use client";

import { useEffect, useState, useCallback } from "react";
import { Activity, TrendingUp, TrendingDown, AlertTriangle, CheckCircle, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type MonthlyData = {
  month: string;
  races: number;
  invested: number;
  payout: number;
  hits: number;
  misses: number;
  pending: number;
  rr: number | null;
  pnl: number;
  cumPnl: number;
  hitRate: number | null;
};

type CalibrationPoint = {
  range: string;
  count: number;
  predicted: number;
  actual: number;
  ratio: number;
};

type MonitorData = {
  monthly: MonthlyData[];
  calibration: CalibrationPoint[];
  streaks: { max: number; current: number; over10: number; over20: number; avg: number };
  rolling: Array<{ idx: number; hitRate: number }>;
  trend: {
    totalRaces: number; totalHits: number;
    overallHR: number; recent200HR: number;
    delta: number; status: string;
  };
};

function SimpleBarChart({ data, getLabel, getValue, getColor, maxVal }: {
  data: Array<Record<string, unknown>>;
  getLabel: (d: Record<string, unknown>) => string;
  getValue: (d: Record<string, unknown>) => number;
  getColor: (d: Record<string, unknown>) => string;
  maxVal?: number;
}) {
  const mx = maxVal ?? Math.max(...data.map(getValue), 1);
  return (
    <div className="space-y-1">
      {data.map((d, i) => {
        const val = getValue(d);
        const pct = Math.max(2, Math.min(100, (val / mx) * 100));
        return (
          <div key={i} className="flex items-center gap-2 text-[11px]">
            <span className="w-16 text-right font-mono text-muted-foreground">{getLabel(d)}</span>
            <div className="h-4 flex-1 overflow-hidden rounded bg-muted">
              <div className={cn("h-full rounded transition-all", getColor(d))} style={{ width: `${pct}%` }} />
            </div>
            <span className="w-14 text-right font-mono font-medium">{val.toFixed(1)}%</span>
          </div>
        );
      })}
    </div>
  );
}

export default function MonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/jrdb/monitor");
      setData(await res.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!data || !data.monthly.length) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Activity className="h-6 w-6" />
          <h2 className="text-2xl font-bold">モデル監視</h2>
        </div>
        <div className="py-12 text-center text-muted-foreground">
          ペーパートレードのデータがありません。先にペーパートレードを記録してください。
        </div>
      </div>
    );
  }

  const t = data.trend;
  const isStable = t.status === "stable";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Activity className="h-6 w-6" />
        <h2 className="text-2xl font-bold">モデル監視</h2>
        <Badge variant="outline" className="text-xs">M7 v25</Badge>
        <Button variant="ghost" size="sm" onClick={fetchData} className="ml-auto text-xs">更新</Button>
      </div>

      {/* Health Status */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Card>
          <CardContent className="pt-4 text-center">
            <div className={cn("text-2xl font-bold", isStable ? "text-green-600" : "text-red-500")}>
              {isStable ? <CheckCircle className="inline h-6 w-6" /> : <AlertTriangle className="inline h-6 w-6" />}
            </div>
            <div className="text-xs text-muted-foreground mt-1">{isStable ? "安定" : "劣化兆候"}</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className="text-2xl font-bold">{t.totalRaces}</div>
            <div className="text-xs text-muted-foreground">総レース</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className="text-2xl font-bold">{t.overallHR.toFixed(1)}%</div>
            <div className="text-xs text-muted-foreground">通算的中率</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className={cn("text-2xl font-bold", t.recent200HR >= t.overallHR ? "text-green-600" : "text-red-500")}>
              {t.recent200HR.toFixed(1)}%
            </div>
            <div className="text-xs text-muted-foreground">直近200R的中率</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4 text-center">
            <div className={cn("text-2xl font-bold", t.delta >= 0 ? "text-green-600" : "text-red-500")}>
              {t.delta >= 0 ? "+" : ""}{t.delta.toFixed(1)}pt
            </div>
            <div className="text-xs text-muted-foreground">トレンド</div>
          </CardContent>
        </Card>
      </div>

      {/* Monthly RR chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">月別回収率</CardTitle>
        </CardHeader>
        <CardContent>
          <SimpleBarChart
            data={data.monthly.filter(m => m.rr !== null) as unknown as Array<Record<string, unknown>>}
            getLabel={(d) => (d as unknown as MonthlyData).month}
            getValue={(d) => (d as unknown as MonthlyData).rr ?? 0}
            getColor={(d) => ((d as unknown as MonthlyData).rr ?? 0) >= 100 ? "bg-green-500" : "bg-red-400"}
            maxVal={200}
          />
          <div className="mt-2 border-t pt-2 text-[10px] text-muted-foreground">
            100%ライン = 損益分岐点。緑 = プラス、赤 = マイナス
          </div>
        </CardContent>
      </Card>

      {/* Cumulative PnL */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">累積損益推移</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-1 items-end h-40">
            {data.monthly.map((m, i) => {
              const maxCum = Math.max(...data.monthly.map(d => Math.abs(d.cumPnl)), 1);
              const height = Math.abs(m.cumPnl) / maxCum * 100;
              const isPositive = m.cumPnl >= 0;
              return (
                <div key={m.month} className="flex-1 flex flex-col items-center justify-end" title={`${m.month}: ${m.cumPnl >= 0 ? "+" : ""}${m.cumPnl.toLocaleString()}円`}>
                  <div
                    className={cn("w-full rounded-t transition-all min-h-[2px]", isPositive ? "bg-green-500" : "bg-red-400")}
                    style={{ height: `${Math.max(2, height)}%` }}
                  />
                  {i % 3 === 0 && (
                    <span className="text-[8px] text-muted-foreground mt-1 -rotate-45 origin-top-left whitespace-nowrap">
                      {m.month.slice(2)}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          <div className="mt-1 text-right text-xs text-muted-foreground">
            累積: {data.monthly.length > 0 && (
              <span className={cn("font-bold", data.monthly[data.monthly.length-1].cumPnl >= 0 ? "text-green-600" : "text-red-500")}>
                {data.monthly[data.monthly.length-1].cumPnl >= 0 ? "+" : ""}
                {(data.monthly[data.monthly.length-1].cumPnl / 10000).toFixed(1)}万円
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        {/* Calibration */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">キャリブレーション</CardTitle>
          </CardHeader>
          <CardContent>
            {data.calibration.length > 0 ? (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="px-2 py-1">予測確率</th>
                    <th className="px-2 py-1 text-right">件数</th>
                    <th className="px-2 py-1 text-right">予測</th>
                    <th className="px-2 py-1 text-right">実測</th>
                    <th className="px-2 py-1 text-right">比率</th>
                  </tr>
                </thead>
                <tbody>
                  {data.calibration.map(c => (
                    <tr key={c.range} className="border-b">
                      <td className="px-2 py-1 font-mono">{c.range}</td>
                      <td className="px-2 py-1 text-right">{c.count}</td>
                      <td className="px-2 py-1 text-right font-mono">{(c.predicted * 100).toFixed(1)}%</td>
                      <td className="px-2 py-1 text-right font-mono">{(c.actual * 100).toFixed(1)}%</td>
                      <td className={cn("px-2 py-1 text-right font-mono font-bold",
                        c.ratio >= 0.8 && c.ratio <= 1.2 ? "text-green-600" : "text-orange-500"
                      )}>
                        {c.ratio.toFixed(2)}x
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center text-sm text-muted-foreground py-4">データ不足</div>
            )}
            <div className="mt-2 text-[10px] text-muted-foreground">
              比率1.0x = 完璧な校正。0.8-1.2xが正常範囲。
            </div>
          </CardContent>
        </Card>

        {/* Streak Analysis */}
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">連敗分析</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-md border p-3 text-center">
                  <div className={cn("text-2xl font-bold", data.streaks.current >= 15 ? "text-red-500" : "")}>
                    {data.streaks.current}
                  </div>
                  <div className="text-[10px] text-muted-foreground">現在の連敗</div>
                </div>
                <div className="rounded-md border p-3 text-center">
                  <div className="text-2xl font-bold">{data.streaks.max}</div>
                  <div className="text-[10px] text-muted-foreground">最大連敗</div>
                </div>
              </div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">10連敗以上</span>
                  <span className="font-mono">{data.streaks.over10}回</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">20連敗以上</span>
                  <span className="font-mono">{data.streaks.over20}回</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">平均連敗</span>
                  <span className="font-mono">{data.streaks.avg.toFixed(1)}</span>
                </div>
              </div>
              {data.streaks.current >= 15 && (
                <div className="rounded bg-red-50 dark:bg-red-950 p-2 text-xs text-red-700 dark:text-red-300 flex items-center gap-1">
                  <AlertTriangle className="h-3 w-3" />
                  {data.streaks.current}連敗中。ベット額を下げることを検討してください。
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Monthly detail table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">月別詳細</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-2 py-1">月</th>
                  <th className="px-2 py-1 text-right">R数</th>
                  <th className="px-2 py-1 text-right">的中</th>
                  <th className="px-2 py-1 text-right">的中率</th>
                  <th className="px-2 py-1 text-right">投資</th>
                  <th className="px-2 py-1 text-right">払戻</th>
                  <th className="px-2 py-1 text-right">回収率</th>
                  <th className="px-2 py-1 text-right">月間損益</th>
                  <th className="px-2 py-1 text-right">累積損益</th>
                </tr>
              </thead>
              <tbody>
                {data.monthly.map(m => {
                  const settled = m.hits + m.misses;
                  return (
                    <tr key={m.month} className="border-b">
                      <td className="px-2 py-1 font-mono">{m.month}</td>
                      <td className="px-2 py-1 text-right">{settled}{m.pending > 0 ? `+${m.pending}` : ""}</td>
                      <td className="px-2 py-1 text-right">{m.hits}</td>
                      <td className="px-2 py-1 text-right font-mono">{m.hitRate?.toFixed(1) ?? "-"}%</td>
                      <td className="px-2 py-1 text-right font-mono">{(m.invested * settled / m.races / 10000).toFixed(1)}万</td>
                      <td className="px-2 py-1 text-right font-mono">{((m.payout ?? 0) / 10000).toFixed(1)}万</td>
                      <td className={cn("px-2 py-1 text-right font-mono font-bold", (m.rr ?? 0) >= 100 ? "text-green-600" : "text-red-500")}>
                        {m.rr?.toFixed(0) ?? "-"}%
                      </td>
                      <td className={cn("px-2 py-1 text-right font-mono", m.pnl >= 0 ? "text-green-600" : "text-red-500")}>
                        {m.pnl >= 0 ? "+" : ""}{(m.pnl / 10000).toFixed(1)}万
                      </td>
                      <td className={cn("px-2 py-1 text-right font-mono font-bold", m.cumPnl >= 0 ? "text-green-600" : "text-red-500")}>
                        {m.cumPnl >= 0 ? "+" : ""}{(m.cumPnl / 10000).toFixed(1)}万
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
