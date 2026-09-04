"use client";

import { useState } from "react";
import { Target, TrendingUp, TrendingDown, CircleDot, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type M7Horse = {
  horseNumber: number;
  horseName: string;
  jockeyName: string;
  idm: number;
  riderIndex: number;
  runStyle: string | null;
  trackFit: number;
  weightStability: number;
  distanceFit: number;
  surfaceFit: number;
  totalScore: number;
  modelProb: number;
  marketProb: number;
  blendedProb: number;
};

type M7Race = {
  raceId: string;
  raceDate: string;
  venueName: string;
  raceNumber: number;
  distance: number;
  surface: string;
  trackCondition: string | null;
  headCount: number;
  horses: M7Horse[];
  top3: number[];
  trioProb: number;
  predBlend: number;
  shouldBet: boolean;
  combination: string;
};

type DatePrediction = {
  date: string;
  total: number;
  shouldBet: number;
  predictions: M7Race[];
};

function PredBlendBadge({ value, shouldBet }: { value: number; shouldBet: boolean }) {
  return (
    <Badge
      variant={shouldBet ? "default" : "outline"}
      className={cn(
        "text-xs font-mono",
        shouldBet && "bg-green-600 hover:bg-green-700"
      )}
    >
      PB={value.toFixed(1)}
    </Badge>
  );
}

function RunStyleBadge({ style }: { style: string | null }) {
  if (!style) return null;
  const colors: Record<string, string> = {
    '逃げ': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200',
    '先行': 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-200',
    '好位差し': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200',
    '差し': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
    '追込': 'bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-200',
    '自在': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  };
  return (
    <span className={cn("rounded px-1 py-0.5 text-[10px] font-medium", colors[style] ?? "bg-gray-100 text-gray-600")}>
      {style}
    </span>
  );
}

function ScoreBar({ value, max, label }: { value: number; max: number; label: string }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const isPositive = value > 0;
  return (
    <div className="flex items-center gap-1 text-[10px]">
      <span className="w-6 text-right text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn("h-full rounded-full", isPositive ? "bg-green-500" : "bg-red-400")}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className={cn("w-8 text-right font-mono", isPositive ? "text-green-600" : "text-red-500")}>
        {value > 0 ? "+" : ""}{value.toFixed(1)}
      </span>
    </div>
  );
}

function RaceCard({ race }: { race: M7Race }) {
  const [expanded, setExpanded] = useState(false);
  const top3Set = new Set(race.top3);

  return (
    <Card className={cn(
      "transition-all",
      race.shouldBet && "ring-2 ring-green-500 dark:ring-green-400"
    )}>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {race.shouldBet ? (
              <Target className="h-4 w-4 text-green-600" />
            ) : (
              <CircleDot className="h-4 w-4 text-muted-foreground" />
            )}
            <CardTitle className="text-sm">
              {race.venueName} {race.raceNumber}R
            </CardTitle>
            <span className="text-xs text-muted-foreground">
              {race.surface}{race.distance}m {race.trackCondition ?? ""} {race.headCount}頭
            </span>
          </div>
          <div className="flex items-center gap-2">
            <PredBlendBadge value={race.predBlend} shouldBet={race.shouldBet} />
            {race.shouldBet && (
              <Badge variant="secondary" className="text-xs">
                三連複 {race.combination} 的中率{(race.trioProb * 100).toFixed(1)}%
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {/* Top 3 summary */}
        <div className="mb-2 flex gap-3">
          {race.horses.slice(0, 3).map((h, i) => (
            <div
              key={h.horseNumber}
              className={cn(
                "flex items-center gap-1.5 rounded px-2 py-1 text-xs",
                top3Set.has(h.horseNumber)
                  ? "bg-green-50 dark:bg-green-950"
                  : "bg-muted"
              )}
            >
              <span className="font-bold">{["◎", "○", "▲"][i]}</span>
              <span className="font-mono text-muted-foreground">#{h.horseNumber}</span>
              <span className="font-medium">{h.horseName}</span>
              <span className="font-mono text-muted-foreground">
                {(h.blendedProb * 100).toFixed(0)}%
              </span>
              <RunStyleBadge style={h.runStyle} />
            </div>
          ))}
        </div>

        {/* Expand toggle */}
        <Button
          variant="ghost"
          size="sm"
          className="h-6 w-full text-xs text-muted-foreground"
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "閉じる" : `全${race.horses.length}頭のスコアを表示`}
        </Button>

        {/* Expanded: Full horse table */}
        {expanded && (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-1 py-1 w-6"></th>
                  <th className="px-1 py-1 w-6">#</th>
                  <th className="px-1 py-1">馬名</th>
                  <th className="px-1 py-1">騎手</th>
                  <th className="px-1 py-1 text-right">IDM</th>
                  <th className="px-1 py-1 text-right">騎手指</th>
                  <th className="px-1 py-1">脚質</th>
                  <th className="px-1 py-1 text-right">馬場</th>
                  <th className="px-1 py-1 text-right">体重</th>
                  <th className="px-1 py-1 text-right">距離</th>
                  <th className="px-1 py-1 text-right font-bold">Score</th>
                  <th className="px-1 py-1 text-right">Model</th>
                  <th className="px-1 py-1 text-right">Market</th>
                  <th className="px-1 py-1 text-right font-bold">Blend</th>
                </tr>
              </thead>
              <tbody>
                {race.horses.map((h, i) => {
                  const isTop3 = top3Set.has(h.horseNumber);
                  return (
                    <tr
                      key={h.horseNumber}
                      className={cn(
                        "border-b",
                        isTop3 && "bg-green-50 dark:bg-green-950 font-medium"
                      )}
                    >
                      <td className="px-1 py-1 text-center">
                        {isTop3 ? ["◎", "○", "▲"][race.top3.indexOf(h.horseNumber)] ?? "" : ""}
                      </td>
                      <td className="px-1 py-1 font-mono">{h.horseNumber}</td>
                      <td className="px-1 py-1 max-w-[100px] truncate">{h.horseName}</td>
                      <td className="px-1 py-1 max-w-[60px] truncate">{h.jockeyName}</td>
                      <td className="px-1 py-1 text-right font-mono">{h.idm.toFixed(0)}</td>
                      <td className="px-1 py-1 text-right font-mono">{h.riderIndex.toFixed(1)}</td>
                      <td className="px-1 py-1"><RunStyleBadge style={h.runStyle} /></td>
                      <td className={cn("px-1 py-1 text-right font-mono", h.trackFit > 0 ? "text-green-600" : h.trackFit < 0 ? "text-red-500" : "")}>
                        {h.trackFit !== 0 ? (h.trackFit > 0 ? "+" : "") + h.trackFit.toFixed(1) : "-"}
                      </td>
                      <td className={cn("px-1 py-1 text-right font-mono", h.weightStability > 0 ? "text-green-600" : h.weightStability < 0 ? "text-red-500" : "")}>
                        {h.weightStability !== 0 ? (h.weightStability > 0 ? "+" : "") + h.weightStability.toFixed(1) : "-"}
                      </td>
                      <td className={cn("px-1 py-1 text-right font-mono", h.distanceFit > 0 ? "text-green-600" : "")}>
                        {h.distanceFit !== 0 ? "+" + h.distanceFit.toFixed(1) : "-"}
                      </td>
                      <td className="px-1 py-1 text-right font-mono font-bold">{h.totalScore.toFixed(1)}</td>
                      <td className="px-1 py-1 text-right font-mono text-muted-foreground">{(h.modelProb * 100).toFixed(1)}%</td>
                      <td className="px-1 py-1 text-right font-mono text-muted-foreground">{(h.marketProb * 100).toFixed(1)}%</td>
                      <td className="px-1 py-1 text-right font-mono font-bold">{(h.blendedProb * 100).toFixed(1)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function M7PredictionPanel() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [data, setData] = useState<DatePrediction | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const handlePredict = async () => {
    setLoading(true);
    try {
      const res = await fetch(`/api/jrdb/predict?date=${date}`);
      const json = await res.json();
      setData(json);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  const displayed = data?.predictions
    ? showAll
      ? data.predictions
      : data.predictions.filter(p => p.shouldBet)
    : [];

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Target className="h-6 w-6" />
        <h2 className="text-2xl font-bold">M7 予測</h2>
        <Badge variant="outline" className="text-xs">v25 Stern補正</Badge>
      </div>

      {/* Date selector */}
      <Card>
        <CardContent className="flex items-center gap-4 pt-6">
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded border px-3 py-2 text-sm"
          />
          <Button onClick={handlePredict} disabled={loading}>
            {loading ? (
              <><Loader2 className="mr-2 h-4 w-4 animate-spin" />予測中...</>
            ) : (
              <><Target className="mr-2 h-4 w-4" />予測実行</>
            )}
          </Button>
          {data && (
            <div className="flex items-center gap-3 text-sm">
              <span className="text-muted-foreground">{data.total}レース</span>
              <Badge className="bg-green-600">{data.shouldBet}レース BET</Badge>
              <Badge variant="outline">{data.total - data.shouldBet}レース SKIP</Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowAll(!showAll)}
                className="text-xs"
              >
                {showAll ? "BETのみ表示" : "全レース表示"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Summary stats */}
      {data && data.predictions.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          <Card>
            <CardContent className="pt-4 text-center">
              <div className="text-2xl font-bold text-green-600">{data.shouldBet}</div>
              <div className="text-xs text-muted-foreground">BETレース</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 text-center">
              <div className="text-2xl font-bold">{data.total - data.shouldBet}</div>
              <div className="text-xs text-muted-foreground">SKIPレース</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 text-center">
              <div className="text-2xl font-bold">
                {(data.shouldBet * 10000).toLocaleString()}円
              </div>
              <div className="text-xs text-muted-foreground">投資額（1万円/R）</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4 text-center">
              <div className="text-2xl font-bold">
                {data.predictions.filter(p => p.shouldBet).length > 0
                  ? (data.predictions
                      .filter(p => p.shouldBet)
                      .reduce((sum, p) => sum + p.trioProb, 0) /
                      data.predictions.filter(p => p.shouldBet).length * 100
                    ).toFixed(1)
                  : "0"}%
              </div>
              <div className="text-xs text-muted-foreground">平均的中率</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Race cards */}
      <div className="space-y-3">
        {displayed.map((race) => (
          <RaceCard key={race.raceId} race={race} />
        ))}
      </div>

      {data && displayed.length === 0 && (
        <div className="py-12 text-center text-muted-foreground">
          {showAll ? "この日のレースデータがありません" : "BET対象のレースがありません"}
        </div>
      )}
    </div>
  );
}
