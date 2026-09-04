"use client";

import { useState, useEffect } from "react";
import { BrainCircuit, Loader2, Trophy, Star, Zap, Shield, ChevronDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type RankedHorse = {
  rank: number;
  mark: string;
  horseNumber: number;
  horseName: string;
  jockeyName: string;
  idm: number;
  riderIndex: number;
  runStyle: string | null;
  totalScore: number;
  blendedProb: number;
  modelProb: number;
  marketProb: number;
  winOdds: number | null;
};

type FunBet = {
  type: string;
  label: string;
  combination: string;
  horses: Array<{ num: number; name: string }>;
  hitRate: number;
  returnRate: number;
  stars: number;
  description: string;
  odds?: number;
};

type PredictionData = {
  race: {
    raceId: string; venueName: string; raceNumber: number;
    raceName: string | null; grade: string | null; distance: number; surface: string;
    trackCondition: string | null; weather: string | null; headCount: number;
  };
  ranking: RankedHorse[];
  predBlend: number;
  shouldBet: boolean;
  trioProb: number;
  funBets: FunBet[];
  comment: string;
};

type RaceListItem = {
  race_id: string;
  race_date: string;
  venue_code: string;
  venue_name: string;
  race_number: number;
  race_name: string | null;
  grade: string | null;
  distance: number;
  surface: string;
  track_condition: string | null;
};

const markColors: Record<string, string> = {
  "◎": "text-red-600 dark:text-red-400",
  "○": "text-blue-600 dark:text-blue-400",
  "▲": "text-green-600 dark:text-green-400",
  "△": "text-orange-500",
  "☆": "text-purple-500",
};

function StarRating({ stars }: { stars: number }) {
  return (
    <span className="text-yellow-500 text-xs">
      {"★".repeat(stars)}{"☆".repeat(3 - stars)}
    </span>
  );
}

function BetCard({ bet }: { bet: FunBet }) {
  const isPlus = bet.returnRate >= 100;
  const isNearEven = bet.returnRate >= 95 && bet.returnRate < 100;

  return (
    <div className={cn(
      "rounded-lg border p-3 transition-all hover:shadow-sm",
      isPlus && "ring-2 ring-green-400 bg-green-50/50 dark:bg-green-950/30",
      isNearEven && "bg-yellow-50/30 dark:bg-yellow-950/20",
    )}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <StarRating stars={bet.stars} />
            <span className="font-bold text-sm">{bet.label}</span>
            {isPlus && <Badge className="bg-green-600 text-[10px]">プラス</Badge>}
            {isNearEven && <Badge variant="outline" className="text-[10px] text-yellow-600 border-yellow-400">トントン</Badge>}
            {bet.odds && <Badge variant="outline" className="text-[10px] font-mono">{bet.odds.toFixed(1)}倍</Badge>}
          </div>
          <p className="text-[11px] text-muted-foreground mt-0.5">{bet.description}</p>
        </div>
        <div className="text-right ml-3">
          <div className={cn("text-base font-bold", isPlus ? "text-green-600" : isNearEven ? "text-yellow-600" : "text-red-500")}>
            {bet.returnRate.toFixed(1)}%
          </div>
          <div className="text-[10px] text-muted-foreground">回収率</div>
        </div>
      </div>
      <div className="flex items-center justify-between">
        <div className="flex gap-1.5 flex-wrap">
          {bet.horses.map(h => (
            <span key={h.num} className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
              {h.num} {h.name}
            </span>
          ))}
        </div>
        <div className="text-[11px] text-muted-foreground whitespace-nowrap ml-2">
          的中率 {bet.hitRate.toFixed(0)}%
        </div>
      </div>
    </div>
  );
}

export default function PredictPage() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [races, setRaces] = useState<RaceListItem[]>([]);
  const [selectedRace, setSelectedRace] = useState<string | null>(null);
  const [prediction, setPrediction] = useState<PredictionData | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAllHorses, setShowAllHorses] = useState(false);

  // Fetch races for date
  useEffect(() => {
    fetch(`/api/jrdb/races?date=${date}`)
      .then(res => res.json())
      .then(data => {
        setRaces(data.races ?? []);
        setSelectedRace(null);
        setPrediction(null);
      })
      .catch(() => setRaces([]));
  }, [date]);

  const handlePredict = async (raceId: string) => {
    setSelectedRace(raceId);
    setLoading(true);
    setPrediction(null);
    setShowAllHorses(false);
    try {
      const res = await fetch(`/api/jrdb/fun-predict?raceId=${raceId}`);
      if (res.ok) setPrediction(await res.json());
    } catch { /* ignore */ }
    finally { setLoading(false); }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <BrainCircuit className="h-6 w-6" />
        <h2 className="text-2xl font-bold">レース予想</h2>
        <Badge variant="outline" className="text-xs">M7 AI予想</Badge>
      </div>

      {/* Date + Race List */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-4 mb-4">
            <input
              type="date"
              value={date}
              onChange={e => setDate(e.target.value)}
              className="rounded border px-3 py-2 text-sm"
            />
            <span className="text-sm text-muted-foreground">{races.length}レース</span>
          </div>
          {races.length > 0 ? (
            <div className="grid gap-2 grid-cols-2 md:grid-cols-4">
              {races.map(r => (
                <button
                  key={r.race_id}
                  onClick={() => handlePredict(r.race_id)}
                  className={cn(
                    "rounded-lg border p-2 text-left text-xs transition-all hover:shadow-sm",
                    selectedRace === r.race_id ? "ring-2 ring-primary bg-primary/5" : "hover:bg-muted/50",
                    r.grade && r.grade.startsWith("G") && "border-2",
                    r.grade === "G1" && "border-red-400",
                    r.grade === "G2" && "border-blue-400",
                    r.grade === "G3" && "border-green-500",
                  )}
                >
                  <div className="flex items-center gap-1">
                    <span className="font-bold">{r.venue_name} {r.race_number}R</span>
                    {r.grade && (
                      <span className={cn("rounded px-1 py-0.5 text-[9px] font-bold",
                        r.grade === "G1" ? "bg-red-500 text-white" :
                        r.grade === "G2" ? "bg-blue-500 text-white" :
                        r.grade === "G3" ? "bg-green-600 text-white" :
                        "bg-orange-400 text-white"
                      )}>{{G1:"GⅠ",G2:"GⅡ",G3:"GⅢ",OP:"OP"}[r.grade] ?? r.grade}</span>
                    )}
                  </div>
                  <div className="text-muted-foreground">
                    {r.surface}{r.distance}m {r.track_condition ?? ""}
                  </div>
                  {r.race_name && (
                    <div className="text-muted-foreground truncate">{r.race_name.replace(/\u3000/g, '').trim()}</div>
                  )}
                </button>
              ))}
            </div>
          ) : (
            <div className="text-center text-sm text-muted-foreground py-4">
              この日のレースデータがありません
            </div>
          )}
        </CardContent>
      </Card>

      {loading && (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {prediction && (
        <>
          {/* Race Info */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="flex items-center gap-2 text-base">
                <Trophy className="h-5 w-5 text-yellow-500" />
                {prediction.race.venueName} {prediction.race.raceNumber}R
                {prediction.race.grade && (
                  <span className={cn("ml-1 rounded px-1.5 py-0.5 text-[10px] font-bold",
                    prediction.race.grade === "G1" ? "bg-red-500 text-white" :
                    prediction.race.grade === "G2" ? "bg-blue-500 text-white" :
                    prediction.race.grade === "G3" ? "bg-green-600 text-white" :
                    "bg-orange-400 text-white"
                  )}>{{G1:"GⅠ",G2:"GⅡ",G3:"GⅢ",OP:"OP"}[prediction.race.grade] ?? prediction.race.grade}</span>
                )}
                {prediction.race.raceName && (
                  <span className="font-normal text-muted-foreground">
                    {prediction.race.raceName.replace(/\u3000/g, '').trim()}
                  </span>
                )}
              </CardTitle>
              <div className="text-xs text-muted-foreground">
                {prediction.race.surface}{prediction.race.distance}m {prediction.race.trackCondition ?? ""} {prediction.race.weather ? `/ ${prediction.race.weather}` : ""} {prediction.race.headCount}頭
              </div>
            </CardHeader>
          </Card>

          {/* AI Comment */}
          {prediction.comment && (
            <Card>
              <CardContent className="pt-4">
                <div className="flex gap-2">
                  <BrainCircuit className="h-4 w-4 text-primary mt-0.5 shrink-0" />
                  <p className="text-sm leading-relaxed">{prediction.comment}</p>
                </div>
              </CardContent>
            </Card>
          )}

          {/* AI Ranking */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Star className="h-4 w-4 text-yellow-500" />
                AI予想ランキング
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1">
                {(showAllHorses ? prediction.ranking : prediction.ranking.slice(0, 5)).map(h => (
                  <div
                    key={h.horseNumber}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm",
                      h.rank <= 3 ? "bg-muted/50" : ""
                    )}
                  >
                    <span className={cn("w-6 text-lg font-bold", markColors[h.mark] ?? "text-muted-foreground")}>
                      {h.mark || h.rank}
                    </span>
                    <span className="w-6 text-right font-mono text-muted-foreground">{h.horseNumber}</span>
                    <span className="flex-1 font-medium">{h.horseName}</span>
                    <span className="text-xs text-muted-foreground">{h.jockeyName}</span>
                    {h.runStyle && (
                      <Badge variant="outline" className="text-[10px]">{h.runStyle}</Badge>
                    )}
                    {h.winOdds && (
                      <span className="w-12 text-right font-mono text-xs text-muted-foreground">{h.winOdds.toFixed(1)}倍</span>
                    )}
                    <span className="w-10 text-right font-mono text-xs text-muted-foreground">IDM {h.idm.toFixed(0)}</span>
                    <div className="w-16">
                      <div className="h-2 rounded-full bg-muted overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", h.rank <= 3 ? "bg-green-500" : "bg-gray-300")}
                          style={{ width: `${Math.min(100, h.blendedProb * 300)}%` }}
                        />
                      </div>
                    </div>
                    <span className="w-10 text-right font-mono text-xs font-bold">{(h.blendedProb * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
              {prediction.ranking.length > 5 && (
                <Button variant="ghost" size="sm" className="w-full mt-2 text-xs" onClick={() => setShowAllHorses(!showAllHorses)}>
                  <ChevronDown className={cn("h-3 w-3 mr-1 transition-transform", showAllHorses && "rotate-180")} />
                  {showAllHorses ? "上位5頭のみ" : `全${prediction.ranking.length}頭を表示`}
                </Button>
              )}
            </CardContent>
          </Card>

          {/* Fun Bets */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <Zap className="h-4 w-4 text-orange-500" />
                おすすめの賭け方
              </CardTitle>
              <p className="text-xs text-muted-foreground">
                回収率は6年間5,350レースのシミュレーション実績。★★★=プラス実績あり
              </p>
            </CardHeader>
            <CardContent className="space-y-2">
              {prediction.funBets.map((bet, i) => (
                <BetCard key={i} bet={bet} />
              ))}
            </CardContent>
          </Card>

          {/* M7 Status */}
          <Card>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <div className="flex items-center gap-2">
                  <Shield className="h-3 w-3" />
                  M7 v25 Stern補正
                </div>
                <div className="flex items-center gap-3">
                  <span>PredBlend: {prediction.predBlend.toFixed(1)}</span>
                  <span>三連複的中率: {(prediction.trioProb * 100).toFixed(1)}%</span>
                  {prediction.shouldBet && (
                    <Badge className="bg-green-600 text-[10px]">M7 BET推奨</Badge>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
