"use client";

import { useEffect, useState, useCallback } from "react";
import { Activity, TrendingUp, TrendingDown, AlertTriangle, RefreshCw, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type DailyData = {
  race_date: string; bets: number; invested: number; payout: number;
  hits: number; misses: number; pending: number;
  avg_ev: number; avg_prob: number; avg_odds: number;
  pnl: number; cumPnl: number; rec: number | null;
};

type BandData = {
  ev_band?: string; odds_band?: string;
  n: number; hits: number; invested: number; payout: number;
  avg_prob: number; avg_odds?: number;
};

type MonitorData = {
  filter: string;
  daily: DailyData[];
  totals: {
    total_bets: number; total_invested: number; total_payout: number;
    hits: number; misses: number; pending: number;
    avg_ev: number; avg_prob: number; avg_odds: number;
    settled: number; settledInvest: number; rec: number | null;
  };
  evBands: BandData[];
  oddsBands: BandData[];
  streaks: { max: number; current: number; avg: number; over10: number; over20: number };
  calibration: Array<{ range: string; n: number; predicted: number; actual: number; ratio: number }>;
};

export default function MonitorPage() {
  const [data, setData] = useState<MonitorData | null>(null);
  const [filter, setFilter] = useState<"all" | "paper" | "live">("all");
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/jrdb/monitor?filter=${filter}`);
      setData(await res.json());
    } catch { /* */ }
    finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading && !data) {
    return <div className="flex items-center justify-center p-12"><Loader2 className="h-6 w-6 animate-spin" /></div>;
  }

  const t = data?.totals;
  const rec = t?.rec;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Activity className="h-6 w-6" />
          モデル監視
        </h1>
        <div className="flex items-center gap-2">
          {(["all", "paper", "live"] as const).map(f => (
            <Button
              key={f}
              size="sm"
              variant={filter === f ? "default" : "outline"}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? "全体" : f === "paper" ? "ペーパー" : "実投票"}
            </Button>
          ))}
          <Button variant="outline" size="sm" onClick={fetchData}>
            <RefreshCw className="mr-1 h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* 全体サマリー */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <StatCard label="投票数" value={t?.total_bets ?? 0} sub={`決済${t?.settled ?? 0} 未決済${t?.pending ?? 0}`} />
        <StatCard label="投資額" value={`${((t?.settledInvest ?? 0) / 1).toLocaleString()}円`} />
        <StatCard label="払戻額" value={`${((t?.total_payout ?? 0) / 1).toLocaleString()}円`} />
        <StatCard
          label="回収率"
          value={rec !== null && rec !== undefined ? `${rec.toFixed(1)}%` : "-"}
          highlight={rec !== null && rec !== undefined && rec >= 100}
          warn={rec !== null && rec !== undefined && rec < 80}
        />
        <StatCard label="的中率" value={t && t.settled > 0 ? `${(t.hits / t.settled * 100).toFixed(1)}%` : "-"} sub={`${t?.hits ?? 0}/${t?.settled ?? 0}`} />
        <StatCard label="平均EV" value={t?.avg_ev?.toFixed(2) ?? "-"} sub={`odds ${t?.avg_odds?.toFixed(1) ?? "-"}`} />
      </div>

      {/* 連敗 */}
      {data && data.streaks.max > 0 && (
        <Card>
          <CardContent className="flex items-center gap-6 py-3">
            {data.streaks.current > 5 && <AlertTriangle className="h-5 w-5 text-yellow-500" />}
            <span className="text-sm">現在連敗: <strong>{data.streaks.current}</strong></span>
            <span className="text-sm text-muted-foreground">最大: {data.streaks.max}</span>
            <span className="text-sm text-muted-foreground">平均: {data.streaks.avg.toFixed(1)}</span>
            <span className="text-sm text-muted-foreground">10連敗以上: {data.streaks.over10}回</span>
          </CardContent>
        </Card>
      )}

      {/* 日別成績 */}
      {data && data.daily.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">日別成績</CardTitle></CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="px-2 py-1 text-left">日付</th>
                    <th className="px-2 py-1 text-right">投票</th>
                    <th className="px-2 py-1 text-right">的中</th>
                    <th className="px-2 py-1 text-right">投資</th>
                    <th className="px-2 py-1 text-right">払戻</th>
                    <th className="px-2 py-1 text-right">回収率</th>
                    <th className="px-2 py-1 text-right">損益</th>
                    <th className="px-2 py-1 text-right">累積</th>
                  </tr>
                </thead>
                <tbody>
                  {data.daily.map(d => (
                    <tr key={d.race_date} className="border-b">
                      <td className="px-2 py-1 font-mono text-xs">{d.race_date}</td>
                      <td className="px-2 py-1 text-right">{d.bets}</td>
                      <td className="px-2 py-1 text-right">{d.hits}/{d.hits + d.misses}</td>
                      <td className="px-2 py-1 text-right">{d.invested.toLocaleString()}</td>
                      <td className="px-2 py-1 text-right">{(d.payout || 0).toLocaleString()}</td>
                      <td className={cn("px-2 py-1 text-right font-medium", d.rec && d.rec >= 100 ? "text-green-600" : "text-red-500")}>
                        {d.rec !== null ? `${d.rec.toFixed(1)}%` : "-"}
                      </td>
                      <td className={cn("px-2 py-1 text-right", d.pnl >= 0 ? "text-green-600" : "text-red-500")}>
                        {d.pnl >= 0 ? "+" : ""}{d.pnl.toLocaleString()}
                      </td>
                      <td className={cn("px-2 py-1 text-right font-medium", d.cumPnl >= 0 ? "text-green-600" : "text-red-500")}>
                        {d.cumPnl >= 0 ? "+" : ""}{d.cumPnl.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* EV帯別・オッズ帯別 */}
      <div className="grid gap-4 lg:grid-cols-2">
        {data && data.evBands.length > 0 && (
          <Card>
            <CardHeader><CardTitle className="text-base">EV帯別成績</CardTitle></CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="px-2 py-1 text-left">EV帯</th>
                    <th className="px-2 py-1 text-right">n</th>
                    <th className="px-2 py-1 text-right">的中</th>
                    <th className="px-2 py-1 text-right">回収率</th>
                  </tr>
                </thead>
                <tbody>
                  {data.evBands.map(b => {
                    const r = b.invested > 0 ? (b.payout / b.invested) * 100 : 0;
                    return (
                      <tr key={b.ev_band} className="border-b">
                        <td className="px-2 py-1 font-mono text-xs">{b.ev_band}</td>
                        <td className="px-2 py-1 text-right">{b.n}</td>
                        <td className="px-2 py-1 text-right">{b.hits}</td>
                        <td className={cn("px-2 py-1 text-right font-medium", r >= 100 ? "text-green-600" : "text-red-500")}>
                          {r.toFixed(1)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}

        {data && data.oddsBands.length > 0 && (
          <Card>
            <CardHeader><CardTitle className="text-base">オッズ帯別成績</CardTitle></CardHeader>
            <CardContent>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-xs text-muted-foreground">
                    <th className="px-2 py-1 text-left">オッズ帯</th>
                    <th className="px-2 py-1 text-right">n</th>
                    <th className="px-2 py-1 text-right">的中</th>
                    <th className="px-2 py-1 text-right">回収率</th>
                  </tr>
                </thead>
                <tbody>
                  {data.oddsBands.map(b => {
                    const r = b.invested > 0 ? (b.payout / b.invested) * 100 : 0;
                    return (
                      <tr key={b.odds_band} className="border-b">
                        <td className="px-2 py-1 font-mono text-xs">{b.odds_band}</td>
                        <td className="px-2 py-1 text-right">{b.n}</td>
                        <td className="px-2 py-1 text-right">{b.hits}</td>
                        <td className={cn("px-2 py-1 text-right font-medium", r >= 100 ? "text-green-600" : "text-red-500")}>
                          {r.toFixed(1)}%
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        )}
      </div>

      {/* キャリブレーション */}
      {data && data.calibration.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-base">キャリブレーション（予測確率 vs 実勝率）</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-xs text-muted-foreground">
                  <th className="px-2 py-1 text-left">確率帯</th>
                  <th className="px-2 py-1 text-right">n</th>
                  <th className="px-2 py-1 text-right">予測</th>
                  <th className="px-2 py-1 text-right">実測</th>
                  <th className="px-2 py-1 text-right">実/予測</th>
                </tr>
              </thead>
              <tbody>
                {data.calibration.map(c => (
                  <tr key={c.range} className="border-b">
                    <td className="px-2 py-1 font-mono text-xs">{c.range}</td>
                    <td className="px-2 py-1 text-right">{c.n}</td>
                    <td className="px-2 py-1 text-right">{(c.predicted * 100).toFixed(2)}%</td>
                    <td className="px-2 py-1 text-right">{(c.actual * 100).toFixed(2)}%</td>
                    <td className={cn("px-2 py-1 text-right font-medium",
                      c.ratio >= 0.9 && c.ratio <= 1.1 ? "text-green-600" : "text-yellow-600"
                    )}>
                      {c.ratio.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {(!data || data.daily.length === 0) && !loading && (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            まだ投票データがありません。リアルタイム投票パイプラインを実行してください。
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatCard({ label, value, sub, highlight, warn }: {
  label: string; value: string | number; sub?: string; highlight?: boolean; warn?: boolean;
}) {
  return (
    <div className="rounded-md border p-3 text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-lg font-bold",
        highlight && "text-green-600",
        warn && "text-red-500"
      )}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}
