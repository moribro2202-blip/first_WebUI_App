"use client";

import { useState, useEffect, useCallback } from "react";
import { FileCheck, Loader2, TrendingUp, TrendingDown, CircleDot, ChevronDown, ChevronUp, Trash2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Trade = {
  id: number;
  race_id: string;
  race_date: string;
  bet_type: string;
  combination: string;
  amount: number;
  odds: number | null;
  ev: number | null;
  ai_score_json: string | null;
  result: string;
  payout: number | null;
  created_at: string;
  settled_at: string | null;
  venue_name: string | null;
  race_number: number | null;
  race_name: string | null;
  surface: string | null;
  distance: number | null;
  grade: string | null;
};

type Stats = {
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
  byDay: Array<{
    day: string;
    invested: number;
    payout: number;
    hits: number;
    count: number;
  }>;
  recent: Trade[];
  recoveryRate: number;
};

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <Card>
      <CardContent className="pt-4 text-center">
        <div className={cn("text-2xl font-bold", color)}>{value}</div>
        <div className="text-xs text-muted-foreground">{label}</div>
        {sub && <div className="text-[10px] text-muted-foreground mt-1">{sub}</div>}
      </CardContent>
    </Card>
  );
}

export default function PaperTradePage() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState(10000);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch("/api/jrdb/paper-trade");
      const data = await res.json();
      setStats(data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  const handleRecord = async () => {
    setActionLoading("record");
    setMessage(null);
    try {
      const res = await fetch("/api/jrdb/paper-trade/m7", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, amount }),
      });
      const data = await res.json();
      if (res.ok) {
        setMessage(`${date}: ${data.recorded}レース記録 (全${data.total}R中、${data.skipped}R SKIP)`);
        fetchStats();
      } else {
        setMessage(data.error ?? "エラー");
      }
    } catch { setMessage("通信エラー"); }
    finally { setActionLoading(null); }
  };

  const handleSettle = async () => {
    setActionLoading("settle");
    setMessage(null);
    try {
      const res = await fetch("/api/jrdb/paper-trade/m7", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date }),
      });
      const data = await res.json();
      if (res.ok) {
        setMessage(`${date}: ${data.settled}件決済 (${data.hits}的中 / 収支: ${data.rr})`);
        fetchStats();
      } else {
        setMessage(data.error ?? "エラー");
      }
    } catch { setMessage("通信エラー"); }
    finally { setActionLoading(null); }
  };

  const t = stats?.total;
  const settled = (t?.hits ?? 0) + (t?.misses ?? 0);
  const invested = t?.total_invested ?? 0;
  const payout = t?.total_payout ?? 0;
  const rr = invested > 0 ? (payout / invested * 100) : 0;
  const pnl = payout - invested;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <FileCheck className="h-6 w-6" />
        <h2 className="text-2xl font-bold">ペーパートレード</h2>
        <Badge variant="outline" className="text-xs">M7 v25</Badge>
      </div>

      {/* Actions */}
      <Card>
        <CardContent className="flex flex-wrap items-center gap-4 pt-6">
          <input
            type="date"
            value={date}
            onChange={e => setDate(e.target.value)}
            className="rounded border px-3 py-2 text-sm"
          />
          <div className="flex items-center gap-1">
            {[1000, 5000, 10000, 30000, 50000].map(v => (
              <button
                key={v}
                onClick={() => setAmount(v)}
                className={cn(
                  "rounded px-2 py-1.5 text-xs border transition-colors",
                  amount === v ? "bg-primary text-primary-foreground" : "hover:bg-muted"
                )}
              >
                {v.toLocaleString()}
              </button>
            ))}
            <input
              type="number"
              value={amount}
              onChange={e => setAmount(Math.max(100, Number(e.target.value)))}
              className="w-20 rounded border px-2 py-1.5 text-xs text-right"
              min={100}
              step={1000}
            />
            <span className="text-xs text-muted-foreground">円/R</span>
          </div>
          <Button onClick={handleRecord} disabled={!!actionLoading} variant="default">
            {actionLoading === "record" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            予測を記録
          </Button>
          <Button onClick={handleSettle} disabled={!!actionLoading} variant="outline">
            {actionLoading === "settle" ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            結果で決済
          </Button>
          <Button
            onClick={async () => {
              if (!confirm(`${date} の記録を削除しますか？`)) return;
              setActionLoading("delete");
              try {
                const res = await fetch("/api/jrdb/paper-trade/m7", {
                  method: "DELETE",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ date }),
                });
                const data = await res.json();
                setMessage(`${date}: ${data.deleted}件削除`);
                fetchStats();
              } catch { setMessage("削除エラー"); }
              finally { setActionLoading(null); }
            }}
            disabled={!!actionLoading}
            variant="ghost"
            size="sm"
            className="text-destructive hover:text-destructive"
          >
            {actionLoading === "delete" ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <Trash2 className="mr-1 h-3 w-3" />}
            削除
          </Button>
          <Button onClick={fetchStats} disabled={loading} variant="ghost" size="sm">
            更新
          </Button>
          {message && (
            <span className="text-sm text-muted-foreground">{message}</span>
          )}
        </CardContent>
      </Card>

      {/* Summary */}
      {t && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard
            label="決済済み"
            value={`${settled}`}
            sub={`未決済: ${t.pending ?? 0}`}
          />
          <StatCard
            label="的中"
            value={`${t.hits ?? 0}`}
            sub={settled > 0 ? `${((t.hits/settled)*100).toFixed(1)}%` : "-"}
            color="text-green-600"
          />
          <StatCard
            label="投資額"
            value={`${invested.toLocaleString()}円`}
          />
          <StatCard
            label="回収率"
            value={rr > 0 ? `${rr.toFixed(1)}%` : "-"}
            color={rr >= 100 ? "text-green-600" : rr > 0 ? "text-red-500" : ""}
          />
          <StatCard
            label="収支"
            value={settled > 0 ? `${pnl >= 0 ? "+" : ""}${pnl.toLocaleString()}円` : "-"}
            color={pnl >= 0 ? "text-green-600" : "text-red-500"}
          />
        </div>
      )}

      {/* Monthly */}
      {stats?.byMonth && stats.byMonth.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">月別成績</CardTitle>
          </CardHeader>
          <CardContent>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-2 py-1">月</th>
                  <th className="px-2 py-1 text-right">R数</th>
                  <th className="px-2 py-1 text-right">的中</th>
                  <th className="px-2 py-1 text-right">投資</th>
                  <th className="px-2 py-1 text-right">払戻</th>
                  <th className="px-2 py-1 text-right">回収率</th>
                  <th className="px-2 py-1 text-right">収支</th>
                </tr>
              </thead>
              <tbody>
                {stats.byMonth.map(m => {
                  const mRR = m.invested > 0 ? (m.payout / m.invested * 100) : 0;
                  const mPnL = (m.payout ?? 0) - m.invested;
                  return (
                    <tr key={m.month} className="border-b">
                      <td className="px-2 py-1 font-mono">{m.month}</td>
                      <td className="px-2 py-1 text-right">{m.count}</td>
                      <td className="px-2 py-1 text-right">{m.hits}</td>
                      <td className="px-2 py-1 text-right">{m.invested.toLocaleString()}</td>
                      <td className="px-2 py-1 text-right">{(m.payout ?? 0).toLocaleString()}</td>
                      <td className={cn("px-2 py-1 text-right font-bold", mRR >= 100 ? "text-green-600" : "text-red-500")}>
                        {mRR.toFixed(1)}%
                      </td>
                      <td className={cn("px-2 py-1 text-right", mPnL >= 0 ? "text-green-600" : "text-red-500")}>
                        {mPnL >= 0 ? "+" : ""}{mPnL.toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Charts */}
      {stats?.byDay && stats.byDay.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2">
          {/* Cumulative PnL chart */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">累積損益推移（日次）</CardTitle>
            </CardHeader>
            <CardContent>
              {(() => {
                let cumPnl = 0;
                const points = stats.byDay.map(d => {
                  cumPnl += (d.payout ?? 0) - d.invested;
                  return { day: d.day, pnl: cumPnl };
                });
                const maxAbs = Math.max(...points.map(p => Math.abs(p.pnl)), 1);
                const chartH = 180;
                const midY = chartH / 2;
                return (
                  <div>
                    <div className="relative" style={{ height: chartH }}>
                      {/* Zero line */}
                      <div className="absolute left-0 right-0 border-t border-dashed border-muted-foreground/30" style={{ top: midY }} />
                      {/* Line chart using SVG */}
                      <svg className="absolute inset-0 w-full h-full" viewBox={`0 0 ${points.length} ${chartH}`} preserveAspectRatio="none">
                        {/* Fill area */}
                        <path
                          d={`M0,${midY} ${points.map((p, i) => `L${i},${midY - (p.pnl / maxAbs) * (midY - 4)}`).join(' ')} L${points.length - 1},${midY} Z`}
                          fill={cumPnl >= 0 ? "rgba(34,197,94,0.15)" : "rgba(239,68,68,0.15)"}
                        />
                        {/* Line */}
                        <polyline
                          points={points.map((p, i) => `${i},${midY - (p.pnl / maxAbs) * (midY - 4)}`).join(' ')}
                          fill="none"
                          stroke={cumPnl >= 0 ? "#22c55e" : "#ef4444"}
                          strokeWidth="1.5"
                          vectorEffect="non-scaling-stroke"
                        />
                      </svg>
                      {/* Hover dots */}
                      <div className="absolute inset-0 flex">
                        {points.map((p, i) => (
                          <div
                            key={p.day}
                            className="flex-1 relative group cursor-pointer"
                            title={`${p.day}: ${p.pnl >= 0 ? "+" : ""}${p.pnl.toLocaleString()}円`}
                          >
                            <div className="hidden group-hover:block absolute z-10 bg-popover text-popover-foreground shadow-md rounded px-2 py-1 text-[10px] whitespace-nowrap -translate-x-1/2 left-1/2"
                              style={{ top: 0 }}>
                              {p.day.slice(5)}: {p.pnl >= 0 ? "+" : ""}{p.pnl.toLocaleString()}円
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="flex justify-between mt-1">
                      <span className="text-[8px] text-muted-foreground">{points[0]?.day}</span>
                      <span className={cn("text-[10px] font-bold", cumPnl >= 0 ? "text-green-600" : "text-red-500")}>
                        {cumPnl >= 0 ? "+" : ""}{cumPnl.toLocaleString()}円
                      </span>
                      <span className="text-[8px] text-muted-foreground">{points[points.length - 1]?.day}</span>
                    </div>
                  </div>
                );
              })()}
            </CardContent>
          </Card>

          {/* Daily RR chart */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">日別回収率</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-0.5 max-h-[250px] overflow-y-auto">
                {stats.byDay.map(d => {
                  const dRR = d.invested > 0 ? (d.payout / d.invested * 100) : 0;
                  const barW = Math.min(100, Math.max(3, dRR / 2));
                  const pnl = (d.payout ?? 0) - d.invested;
                  return (
                    <div key={d.day} className="flex items-center gap-2 text-[10px]">
                      <span className="w-16 text-right font-mono text-muted-foreground">{d.day.slice(5)}</span>
                      <div className="h-3 flex-1 overflow-hidden rounded bg-muted relative">
                        <div className="absolute top-0 bottom-0 w-px bg-muted-foreground/40" style={{ left: '50%' }} />
                        <div
                          className={cn("h-full rounded transition-all", dRR >= 100 ? "bg-green-500" : "bg-red-400")}
                          style={{ width: `${barW}%` }}
                        />
                      </div>
                      <span className={cn("w-10 text-right font-mono", dRR >= 100 ? "text-green-600" : "text-red-500")}>
                        {dRR > 0 ? `${dRR.toFixed(0)}%` : "0%"}
                      </span>
                      <span className={cn("w-16 text-right font-mono text-[9px]", pnl >= 0 ? "text-green-600" : "text-red-500")}>
                        {pnl >= 0 ? "+" : ""}{pnl.toLocaleString()}
                      </span>
                    </div>
                  );
                })}
              </div>
              <div className="mt-1 text-[9px] text-muted-foreground text-center">縦線 = 100%（損益分岐点）</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Recent trades */}
      {stats?.recent && stats.recent.length > 0 && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm">直近の取引</CardTitle>
            <Button variant="ghost" size="sm" onClick={() => setShowAll(!showAll)} className="text-xs">
              {showAll ? <><ChevronUp className="mr-1 h-3 w-3"/>少なく</> : <><ChevronDown className="mr-1 h-3 w-3"/>全て表示</>}
            </Button>
          </CardHeader>
          <CardContent>
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-2 py-1">日付</th>
                  <th className="px-2 py-1">レース</th>
                  <th className="px-2 py-1">買い目</th>
                  <th className="px-2 py-1 text-right">オッズ</th>
                  <th className="px-2 py-1 text-right">投資</th>
                  <th className="px-2 py-1 text-center">結果</th>
                  <th className="px-2 py-1 text-right">収支</th>
                </tr>
              </thead>
              <tbody>
                {(showAll ? stats.recent : stats.recent.slice(0, 100)).map(trade => {
                  let scoreInfo = null;
                  try { scoreInfo = trade.ai_score_json ? JSON.parse(trade.ai_score_json) : null; } catch {}
                  return (
                    <tr key={trade.id} className="border-b">
                      <td className="px-2 py-1 font-mono text-muted-foreground">{trade.race_date}</td>
                      <td className="px-2 py-1">
                        {trade.venue_name ? (
                          <div className="flex items-center gap-1 flex-wrap">
                            <span>{trade.venue_name}{trade.race_number}R</span>
                            {trade.grade && (
                              <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-bold",
                                trade.grade === "G1" ? "bg-red-500 text-white" :
                                trade.grade === "G2" ? "bg-blue-500 text-white" :
                                trade.grade === "G3" ? "bg-green-600 text-white" :
                                "bg-orange-400 text-white"
                              )}>{{G1:"GⅠ",G2:"GⅡ",G3:"GⅢ",OP:"OP"}[trade.grade] ?? trade.grade}</span>
                            )}
                            {trade.race_name && (
                              <span className="text-[10px] text-muted-foreground truncate max-w-[150px]">
                                {trade.race_name}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="font-mono text-muted-foreground">{trade.race_id}</span>
                        )}
                      </td>
                      <td className="px-2 py-1">
                        <span className="font-mono">{trade.combination}</span>
                        {scoreInfo?.predBlend && (
                          <span className="ml-1 text-muted-foreground">PB={scoreInfo.predBlend.toFixed(1)}</span>
                        )}
                      </td>
                      <td className="px-2 py-1 text-right font-mono">{trade.odds?.toFixed(1) ?? "-"}</td>
                      <td className="px-2 py-1 text-right font-mono text-muted-foreground">{trade.amount.toLocaleString()}</td>
                      <td className="px-2 py-1 text-center">
                        {trade.result === "hit" && <Badge className="bg-green-600 text-[10px]">的中</Badge>}
                        {trade.result === "miss" && <Badge variant="outline" className="text-[10px]">不的中</Badge>}
                        {trade.result === "pending" && <Badge variant="secondary" className="text-[10px]">未決済</Badge>}
                      </td>
                      <td className={cn("px-2 py-1 text-right font-mono", trade.payout && trade.payout > 0 ? "text-green-600 font-bold" : "")}>
                        {trade.result === "hit" ? `+${((trade.payout ?? 0) - trade.amount).toLocaleString()}` : trade.result === "miss" ? `-${trade.amount.toLocaleString()}` : "-"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {(!stats?.recent || stats.recent.length === 0) && (
        <div className="py-12 text-center text-muted-foreground">
          まだ取引がありません。日付を選んで「予測を記録」してください。
        </div>
      )}
    </div>
  );
}
