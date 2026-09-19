"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Zap, Clock, TrendingUp, TrendingDown, CircleDot,
  RefreshCw, Loader2, Settings,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Config = {
  mode: string;
  amount: string;
  ev_threshold: string;
  ev_threshold_trio: string;
  odds_min: string;
  odds_max: string;
};

type Bet = {
  id: number;
  venue_name: string;
  race_number: number;
  horse_number: number | string;
  bet_type: string | null;
  amount: number;
  odds_at_bet: number;
  model_prob: number;
  ev: number;
  move: number;
  status: string;
  is_live: number;
  result: string | null;
  payout: number | null;
  winner_number: number | null;
  created_at: string;
};

type Stats = {
  totalBets: number;
  totalInvested: number;
  totalPayout: number;
  hits: number;
  misses: number;
  pending: number;
  oddsCount: number;
};

type Race = {
  race_id: string;
  venue_name: string;
  race_number: number;
  surface: string;
  distance: number;
  start_time: string;
  deadline: string;
  race_name: string | null;
  grade: string | null;
  snapshotCount: number;
  betStatus: string;
  betCount: number;
  topEv: number | null;
  topHorse: number | null;
  topOdds: number | null;
  winner: number | null;
  winnerOdds: number | null;
};

type Prediction = {
  race_id: string;
  venue_name: string;
  race_number: number;
  horse_number: number;
  odds: number;
  model_prob: number;
  ev: number;
  move: number;
  should_bet: number;
  created_at: string;
};

type Snapshot = {
  venue_name: string;
  race_number: number;
  snapshot_label: string;
  horses: number;
  min_odds: number;
  snapshot_time: string;
};

type OddsDetail = {
  race_id: string;
  venue_name: string;
  race_number: number;
  snapshot_label: string;
  horse_number: number;
  odds: number;
  snapshot_time: string;
};

export default function RealtimePage() {
  const [config, setConfig] = useState<Config | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [bets, setBets] = useState<Bet[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [oddsDetail, setOddsDetail] = useState<OddsDetail[]>([]);
  const [races, setRaces] = useState<Race[]>([]);
  const [now, setNow] = useState(new Date());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [editMode, setEditMode] = useState<string>("");
  const [editAmount, setEditAmount] = useState<string>("");
  const [editThreshold, setEditThreshold] = useState<string>("");
  const [editThresholdTrio, setEditThresholdTrio] = useState<string>("");

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch("/api/jrdb/realtime");
      if (!res.ok) return;
      const data = await res.json();
      setConfig(data.config);
      setStats(data.stats);
      setBets(data.bets || []);
      setSnapshots(data.snapshots || []);
      setPredictions(data.predictions || []);
      setOddsDetail(data.oddsDetail || []);
      setRaces(data.races || []);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // 1秒ごとにカウントダウン更新
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const updateConfig = async (updates: Partial<Config>) => {
    setSaving(true);
    try {
      const res = await fetch("/api/jrdb/realtime", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      if (res.ok) {
        const data = await res.json();
        setConfig(data.config);
      }
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12">
        <Loader2 className="h-6 w-6 animate-spin" />
      </div>
    );
  }

  const isLive = config?.mode === "live";
  const returnRate = stats && stats.totalInvested > 0
    ? (stats.totalPayout / stats.totalInvested * 100)
    : null;

  // スナップショットをレースごとにグループ化
  const raceSnapshots = new Map<string, Snapshot[]>();
  for (const s of snapshots) {
    const key = `${s.venue_name}${s.race_number}R`;
    if (!raceSnapshots.has(key)) raceSnapshots.set(key, []);
    raceSnapshots.get(key)!.push(s);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Zap className="h-6 w-6" />
          リアルタイム投票
        </h1>
        <Button variant="outline" size="sm" onClick={fetchData}>
          <RefreshCw className="mr-1 h-4 w-4" />
          更新
        </Button>
      </div>

      {/* 設定 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Settings className="h-4 w-4" />
            設定
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-4">
            {/* モード切替 */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">モード:</span>
              <Button
                size="sm"
                variant={isLive ? "destructive" : "outline"}
                onClick={() => updateConfig({ mode: isLive ? "paper" : "live" })}
                disabled={saving}
              >
                {isLive ? "★ 実投票" : "ペーパー"}
              </Button>
            </div>

            {/* 金額 */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">金額:</span>
              {editMode === "amount" ? (
                <form
                  className="flex gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    updateConfig({ amount: editAmount });
                    setEditMode("");
                  }}
                >
                  <input
                    type="number"
                    value={editAmount}
                    onChange={(e) => setEditAmount(e.target.value)}
                    className="w-24 rounded border px-2 py-1 text-sm"
                    autoFocus
                  />
                  <Button size="sm" type="submit" disabled={saving}>OK</Button>
                </form>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => { setEditAmount(config?.amount || "100"); setEditMode("amount"); }}
                >
                  {Number(config?.amount || 0).toLocaleString()}円
                </Button>
              )}
            </div>

            {/* 単勝EV閾値 */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">単勝EV閾値:</span>
              {editMode === "threshold" ? (
                <form
                  className="flex gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    updateConfig({ ev_threshold: editThreshold });
                    setEditMode("");
                  }}
                >
                  <input
                    type="number"
                    step="0.01"
                    value={editThreshold}
                    onChange={(e) => setEditThreshold(e.target.value)}
                    className="w-20 rounded border px-2 py-1 text-sm"
                    autoFocus
                  />
                  <Button size="sm" type="submit" disabled={saving}>OK</Button>
                </form>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => { setEditThreshold(config?.ev_threshold || "1.20"); setEditMode("threshold"); }}
                >
                  {config?.ev_threshold}
                </Button>
              )}
            </div>

            {/* トリオEV閾値 */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">トリオEV閾値:</span>
              {editMode === "threshold_trio" ? (
                <form
                  className="flex gap-1"
                  onSubmit={(e) => {
                    e.preventDefault();
                    updateConfig({ ev_threshold_trio: editThresholdTrio });
                    setEditMode("");
                  }}
                >
                  <input
                    type="number"
                    step="0.01"
                    value={editThresholdTrio}
                    onChange={(e) => setEditThresholdTrio(e.target.value)}
                    className="w-20 rounded border px-2 py-1 text-sm"
                    autoFocus
                  />
                  <Button size="sm" type="submit" disabled={saving}>OK</Button>
                </form>
              ) : (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => { setEditThresholdTrio(config?.ev_threshold_trio || "1.0"); setEditMode("threshold_trio"); }}
                >
                  {config?.ev_threshold_trio || "1.0"}
                </Button>
              )}
            </div>

            {/* オッズ帯 */}
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">オッズ帯:</span>
              <span className="text-sm">{config?.odds_min}〜{config?.odds_max}倍</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 本日の成績 */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-6">
        <StatCard label="投票数" value={stats?.totalBets ?? 0} />
        <StatCard label="投資額" value={stats?.totalInvested ?? 0} suffix="円" />
        <StatCard label="払戻額" value={stats?.totalPayout ?? 0} suffix="円" />
        <StatCard
          label="回収率"
          value={returnRate !== null ? `${returnRate.toFixed(1)}%` : "-"}
          highlight={returnRate !== null && returnRate >= 100}
        />
        <StatCard label="的中" value={stats?.hits ?? 0} suffix={`/${(stats?.hits ?? 0) + (stats?.misses ?? 0)}`} />
        <StatCard label="記録数" value={stats?.oddsCount ?? 0} suffix="オッズ" />
      </div>

      {/* レース一覧 */}
      {races.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4" />
              本日のレース（{races.length}R）
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1">
              {(() => {
                // 会場ごとにグループ化
                const byVenue = new Map<string, Race[]>();
                for (const r of races) {
                  if (!byVenue.has(r.venue_name)) byVenue.set(r.venue_name, []);
                  byVenue.get(r.venue_name)!.push(r);
                }
                return Array.from(byVenue.entries()).map(([venue, venueRaces]) => (
                  <div key={venue}>
                    <div className="mb-1 mt-2 text-xs font-medium text-muted-foreground">{venue}</div>
                    <div className="grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-3">
                      {venueRaces.map((r) => {
                        const deadlineDate = parseTimeToDate(r.deadline);
                        const startDate = parseTimeToDate(r.start_time);
                        const diffSec = deadlineDate ? Math.floor((deadlineDate.getTime() - now.getTime()) / 1000) : null;
                        const isFinished = startDate ? now >= startDate : false;
                        const isClose = diffSec !== null && diffSec > 0 && diffSec <= 300;
                        const isVeryClose = diffSec !== null && diffSec > 0 && diffSec <= 60;

                        return (
                          <div
                            key={r.race_id}
                            className={cn(
                              "flex items-center justify-between rounded-md border px-3 py-2 text-sm",
                              r.winner !== null && "bg-muted/50",
                              isVeryClose && "border-red-400 bg-red-50 dark:bg-red-950",
                              isClose && !isVeryClose && "border-yellow-400 bg-yellow-50 dark:bg-yellow-950",
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <span className="font-medium">{r.race_number}R</span>
                              <span className="text-xs text-muted-foreground">
                                {r.surface}{r.distance}m
                              </span>
                              {r.race_name && (
                                <span className="text-xs">{r.race_name.slice(0, 6)}</span>
                              )}
                              {r.grade && (
                                <Badge variant="outline" className="text-xs px-1 py-0">{r.grade}</Badge>
                              )}
                            </div>
                            <div className="flex items-center gap-2 text-right">
                              <div className="text-xs">
                                <div>発走 {r.start_time}</div>
                                <div className="text-muted-foreground">締切 {r.deadline}</div>
                              </div>
                              <div className="w-16 text-right">
                                {r.winner !== null ? (
                                  <span className="text-xs text-muted-foreground">
                                    1着:{r.winner}番
                                  </span>
                                ) : isFinished ? (
                                  <span className="text-xs text-muted-foreground">走行中</span>
                                ) : diffSec !== null && diffSec > 0 ? (
                                  <span className={cn(
                                    "font-mono text-xs font-bold",
                                    isVeryClose ? "text-red-600" : isClose ? "text-yellow-600" : "text-muted-foreground"
                                  )}>
                                    {formatCountdown(diffSec)}
                                  </span>
                                ) : (
                                  <span className="text-xs text-muted-foreground">締切済</span>
                                )}
                              </div>
                              {/* 投票状況 */}
                              <div className="flex flex-col items-end gap-0.5">
                                <div className="flex gap-0.5">
                                  {r.snapshotCount > 0 && (
                                    <Badge variant="secondary" className="text-xs px-1 py-0">
                                      T{r.snapshotCount}
                                    </Badge>
                                  )}
                                  {r.betStatus === "live_bet" && (
                                    <Badge variant="destructive" className="text-xs px-1 py-0">実投票</Badge>
                                  )}
                                  {r.betStatus === "paper_bet" && (
                                    <Badge className="text-xs px-1 py-0 bg-blue-500">PAPER</Badge>
                                  )}
                                  {r.betStatus === "no_bet" && (
                                    <Badge variant="outline" className="text-xs px-1 py-0">見送</Badge>
                                  )}
                                </div>
                                {r.topEv !== null && (
                                  <span className={cn("text-xs font-mono",
                                    r.topEv >= 1.2 ? "text-green-600 font-bold" : "text-muted-foreground"
                                  )}>
                                    EV{r.topEv.toFixed(2)} #{r.topHorse}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ));
              })()}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 投票履歴（レースごとにグループ化） */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">投票履歴</CardTitle>
        </CardHeader>
        <CardContent>
          {bets.length === 0 ? (
            <p className="text-sm text-muted-foreground">本日の投票はまだありません</p>
          ) : (
            <div className="space-y-4">
              {(() => {
                // レースごとにグループ化
                const groups: Record<string, typeof bets> = {};
                for (const bet of bets) {
                  const key = `${bet.venue_name}${bet.race_number}R`;
                  if (!groups[key]) groups[key] = [];
                  groups[key].push(bet);
                }
                return Object.entries(groups).map(([raceLabel, raceBets]) => {
                  const totalAmount = raceBets.reduce((s, b) => s + b.amount, 0);
                  const totalPayout = raceBets.reduce((s, b) => s + (b.payout || 0), 0);
                  const hasHit = raceBets.some(b => b.result === "hit");
                  const hasMiss = raceBets.some(b => b.result === "miss");
                  const isLive = raceBets.some(b => b.is_live);
                  const trioEv = raceBets.find(b => b.bet_type === "sanrenpuku")?.ev;
                  return (
                    <div
                      key={raceLabel}
                      className={cn(
                        "rounded-md border text-sm",
                        hasHit && "border-green-300 bg-green-50 dark:border-green-800 dark:bg-green-950",
                        hasMiss && !hasHit && "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950",
                      )}
                    >
                      {/* レースヘッダー */}
                      <div className="flex items-center justify-between border-b px-3 py-2">
                        <div className="flex items-center gap-2">
                          {hasHit ? (
                            <TrendingUp className="h-4 w-4 text-green-600" />
                          ) : hasMiss ? (
                            <TrendingDown className="h-4 w-4 text-red-500" />
                          ) : (
                            <CircleDot className="h-4 w-4 text-muted-foreground" />
                          )}
                          <span className="font-medium">{raceLabel}</span>
                          <Badge variant={isLive ? "destructive" : "secondary"} className="text-xs">
                            {isLive ? "実投票" : "PAPER"}
                          </Badge>
                          {trioEv != null && (
                            <span className="text-xs text-muted-foreground">トリオEV={trioEv.toFixed(2)}</span>
                          )}
                        </div>
                        <div className="text-right">
                          <span className="font-medium">{raceBets.length}点 {totalAmount.toLocaleString()}円</span>
                          {totalPayout > 0 && (
                            <span className="ml-2 font-bold text-green-600">→ {totalPayout.toLocaleString()}円</span>
                          )}
                        </div>
                      </div>
                      {/* 買い目テーブル */}
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b text-muted-foreground">
                            <th className="px-3 py-1 text-left">券種</th>
                            <th className="px-2 py-1 text-left">組合せ</th>
                            <th className="px-2 py-1 text-right">オッズ</th>
                            <th className="px-2 py-1 text-right">EV</th>
                            <th className="px-2 py-1 text-right">金額</th>
                            <th className="px-2 py-1 text-right">結果</th>
                          </tr>
                        </thead>
                        <tbody>
                          {raceBets.map((bet) => (
                            <tr key={bet.id} className="border-b last:border-0">
                              <td className="px-3 py-1">{formatBetType(bet.bet_type, bet.status)}</td>
                              <td className="px-2 py-1 font-mono">{bet.horse_number}</td>
                              <td className="px-2 py-1 text-right">{Number(bet.odds_at_bet).toFixed(1)}</td>
                              <td className="px-2 py-1 text-right">{bet.ev.toFixed(2)}</td>
                              <td className="px-2 py-1 text-right">{bet.amount}円</td>
                              <td className="px-2 py-1 text-right">
                                {bet.result === "hit" ? (
                                  <span className="font-bold text-green-600">{bet.payout?.toLocaleString()}円</span>
                                ) : bet.result === "miss" ? (
                                  <span className="text-red-500">×</span>
                                ) : (
                                  <span className="text-muted-foreground">—</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                });
              })()}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* EV予測一覧 */}
      {predictions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <TrendingUp className="h-4 w-4" />
              EV予測一覧（レース別 Top5）
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              {(() => {
                // レースごとにグループ化
                const byRace = new Map<string, Prediction[]>();
                for (const p of predictions) {
                  const key = `${p.venue_name}${p.race_number}R`;
                  if (!byRace.has(key)) byRace.set(key, []);
                  byRace.get(key)!.push(p);
                }
                return Array.from(byRace.entries()).map(([raceLabel, preds]) => (
                  <div key={raceLabel} className="rounded-md border">
                    <div className="border-b bg-muted/50 px-3 py-2 text-sm font-medium">{raceLabel}</div>
                    <div className="divide-y">
                      {preds.slice(0, 5).map((p, i) => (
                        <div
                          key={i}
                          className={cn(
                            "flex items-center justify-between px-3 py-1.5 text-sm",
                            p.should_bet && "bg-yellow-50 dark:bg-yellow-950 font-medium"
                          )}
                        >
                          <div className="flex items-center gap-3">
                            {p.should_bet ? (
                              <Badge variant="destructive" className="text-xs">BET</Badge>
                            ) : (
                              <span className="w-8 text-center text-xs text-muted-foreground">{i + 1}</span>
                            )}
                            <span>馬番{p.horse_number}</span>
                            <span className="text-muted-foreground">{p.odds}倍</span>
                          </div>
                          <div className="flex items-center gap-4 text-xs">
                            <span>P={p.model_prob.toFixed(3)}</span>
                            <span className={cn("font-mono", p.ev >= 1.20 ? "text-green-600 font-bold" : p.ev >= 1.0 ? "text-blue-600" : "text-muted-foreground")}>
                              EV={p.ev.toFixed(3)}
                            </span>
                            <span className={cn(p.move > 0.01 ? "text-green-600" : p.move < -0.01 ? "text-red-500" : "text-muted-foreground")}>
                              move={p.move >= 0 ? "+" : ""}{p.move.toFixed(3)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ));
              })()}
            </div>
          </CardContent>
        </Card>
      )}

      {/* オッズ記録（全馬表示） */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Clock className="h-4 w-4" />
            オッズ記録（T-5 / T-2 / T-1 全馬）
          </CardTitle>
        </CardHeader>
        <CardContent>
          {oddsDetail.length === 0 ? (
            <p className="text-sm text-muted-foreground">まだオッズが記録されていません</p>
          ) : (
            <div className="space-y-4">
              {(() => {
                // race_id でグループ化
                const byRace = new Map<string, { label: string; horses: Set<number>; data: Map<string, Map<number, number>> }>();
                for (const d of oddsDetail) {
                  const key = d.race_id;
                  if (!byRace.has(key)) {
                    byRace.set(key, {
                      label: `${d.venue_name}${d.race_number}R`,
                      horses: new Set(),
                      data: new Map(),
                    });
                  }
                  const race = byRace.get(key)!;
                  race.horses.add(d.horse_number);
                  if (!race.data.has(d.snapshot_label)) race.data.set(d.snapshot_label, new Map());
                  race.data.get(d.snapshot_label)!.set(d.horse_number, d.odds);
                }
                return Array.from(byRace.entries()).map(([raceId, race]) => {
                  const horses = Array.from(race.horses).sort((a, b) => a - b);
                  const labels = Array.from(race.data.keys());
                  return (
                    <div key={raceId} className="rounded-md border">
                      <div className="border-b bg-muted/50 px-3 py-1.5 text-sm font-medium">
                        {race.label}（{horses.length}頭）
                      </div>
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b text-muted-foreground">
                              <th className="px-2 py-1 text-left">馬番</th>
                              {["5min","4min","3min","2min","1min"].filter(l => labels.includes(l)).map(l => (
                                <th key={l} className="px-2 py-1 text-right">{l.replace("min","分前")}</th>
                              ))}
                              {labels.includes("confirmed") && <th className="px-2 py-1 text-right">確定</th>}
                              {labels.includes("5min") && labels.includes("3min") && (
                                <th className="px-2 py-1 text-right">5→3分変動</th>
                              )}
                            </tr>
                          </thead>
                          <tbody>
                            {horses.map(hn => {
                              const o5 = race.data.get("5min")?.get(hn);
                              const o4 = race.data.get("4min")?.get(hn);
                              const o3 = race.data.get("3min")?.get(hn);
                              const o2 = race.data.get("2min")?.get(hn);
                              const o1 = race.data.get("1min")?.get(hn);
                              const oC = race.data.get("confirmed")?.get(hn);
                              // 5分前→3分前のオッズ変化率（move_5to3）
                              const moveVal = o5 && o3 && o5 > 0 ? ((o3 - o5) / o5 * 100) : null;
                              return (
                                <tr key={hn} className="border-b hover:bg-muted/30">
                                  <td className="px-2 py-0.5 font-medium">{hn}</td>
                                  {[["5min",o5],["4min",o4],["3min",o3],["2min",o2],["1min",o1]].filter(([l]) => labels.includes(l as string)).map(([l,o]) => (
                                    <td key={l as string} className={cn("px-2 py-0.5 text-right font-mono", l === "3min" ? "font-medium" : "text-muted-foreground")}>
                                      {(o as number | undefined)?.toFixed(1) ?? "-"}
                                    </td>
                                  ))}
                                  {labels.includes("confirmed") && (
                                    <td className="px-2 py-0.5 text-right font-mono font-medium">{oC?.toFixed(1) ?? "-"}</td>
                                  )}
                                  {(labels.includes("5min") && labels.includes("3min")) && (
                                    <td className={cn("px-2 py-0.5 text-right font-mono font-medium",
                                      moveVal !== null && moveVal < -2 ? "text-green-600" :
                                      moveVal !== null && moveVal > 2 ? "text-red-500" : "text-muted-foreground"
                                    )}>
                                      {moveVal !== null ? `${moveVal >= 0 ? "+" : ""}${moveVal.toFixed(1)}%` : "-"}
                                    </td>
                                  )}
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function formatBetType(betType: string | null, status: string): string {
  const isPaper = status?.includes("paper");
  const suffix = isPaper ? "(P)" : "";
  switch (betType) {
    case "win": return `単勝${suffix}`;
    case "sanrenpuku": return `三連複${suffix}`;
    case "sanrentan": return `三連単${suffix}`;
    default: return `${betType || "単勝"}${suffix}`;
  }
}

function parseTimeToDate(timeStr: string | null): Date | null {
  if (!timeStr || !timeStr.includes(":")) return null;
  const [h, m] = timeStr.split(":").map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d;
}

function formatCountdown(totalSec: number): string {
  if (totalSec <= 0) return "0:00";
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function StatCard({
  label,
  value,
  suffix,
  highlight,
}: {
  label: string;
  value: number | string;
  suffix?: string;
  highlight?: boolean;
}) {
  return (
    <div className="rounded-md border p-3 text-center">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("text-lg font-bold", highlight && "text-green-600")}>
        {typeof value === "number" ? value.toLocaleString() : value}
        {suffix && <span className="text-xs font-normal text-muted-foreground">{suffix}</span>}
      </p>
    </div>
  );
}
