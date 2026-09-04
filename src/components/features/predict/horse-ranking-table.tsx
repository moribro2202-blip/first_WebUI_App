"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { AiRank } from "@/types";

type ExtendedHorse = {
  horseNumber: number;
  horseName: string;
  aiScore: number;
  rank: AiRank;
  reason: string;
  oddsValue?: string;
  winProb?: number; // 勝率（%）
};

const rankColors: Record<AiRank, string> = {
  "◎": "bg-red-500 text-white",
  "○": "bg-orange-500 text-white",
  "▲": "bg-yellow-500 text-white",
  "△": "bg-blue-500 text-white",
  "☆": "bg-gray-500 text-white",
};

const oddsValueColors: Record<string, string> = {
  "A+": "bg-red-600 text-white",
  "A": "bg-orange-500 text-white",
  "B": "bg-gray-400 text-white",
  "C": "bg-blue-400 text-white",
  "D": "bg-gray-300 text-gray-600",
};

function ScoreBar({ score }: { score: number }) {
  const pct = Math.max(0, Math.min(100, ((score - 35) / 40) * 100));
  const color =
    score >= 65 ? "bg-red-500" : score >= 55 ? "bg-orange-400" : "bg-blue-400";

  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-20 rounded-full bg-muted">
        <div className={cn("h-full rounded-full", color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-sm font-bold">{score}</span>
    </div>
  );
}

type Props = {
  horses: ExtendedHorse[];
};

export function HorseRankingTable({ horses }: Props) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="w-16">印</TableHead>
          <TableHead className="w-16">馬番</TableHead>
          <TableHead>馬名</TableHead>
          <TableHead className="w-32">AI偏差値</TableHead>
          <TableHead className="w-20">勝率</TableHead>
          <TableHead className="w-20">歪み</TableHead>
          <TableHead>理由</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {horses.map((horse) => (
          <TableRow key={horse.horseNumber}>
            <TableCell>
              <Badge className={cn("text-base", rankColors[horse.rank])}>
                {horse.rank}
              </Badge>
            </TableCell>
            <TableCell className="font-bold">{horse.horseNumber}</TableCell>
            <TableCell className="font-medium">{horse.horseName}</TableCell>
            <TableCell>
              <ScoreBar score={horse.aiScore} />
            </TableCell>
            <TableCell>
              {horse.winProb !== undefined && (
                <span
                  className={cn(
                    "text-sm font-bold",
                    horse.winProb >= 20
                      ? "text-red-500"
                      : horse.winProb >= 10
                        ? "text-orange-500"
                        : "text-muted-foreground"
                  )}
                >
                  {horse.winProb.toFixed(1)}%
                </span>
              )}
            </TableCell>
            <TableCell>
              {horse.oddsValue && (
                <Badge className={cn("text-xs", oddsValueColors[horse.oddsValue] ?? "bg-gray-400 text-white")}>
                  {horse.oddsValue}
                </Badge>
              )}
            </TableCell>
            <TableCell className="text-sm text-muted-foreground">
              {horse.reason}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
