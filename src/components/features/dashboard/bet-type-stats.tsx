"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BET_TYPE_LABELS } from "@/types";
import type { PerformanceStats } from "@/types";

export function BetTypeStats({ stats }: { stats: PerformanceStats[] }) {
  const active = stats.filter((s) => s.totalBets > 0);

  if (active.length === 0) {
    return null;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">馬券種別成績</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>券種</TableHead>
              <TableHead className="text-right">購入数</TableHead>
              <TableHead className="text-right">的中数</TableHead>
              <TableHead className="text-right">的中率</TableHead>
              <TableHead className="text-right">回収率</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {active.map((s) => (
              <TableRow key={s.betType}>
                <TableCell className="font-medium">
                  {BET_TYPE_LABELS[s.betType]}
                </TableCell>
                <TableCell className="text-right">{s.totalBets}</TableCell>
                <TableCell className="text-right">{s.wins}</TableCell>
                <TableCell className="text-right">{s.hitRate.toFixed(1)}%</TableCell>
                <TableCell
                  className={`text-right font-medium ${s.recoveryRate >= 100 ? "text-green-600" : ""}`}
                >
                  {s.recoveryRate.toFixed(1)}%
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
