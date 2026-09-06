"use client";

import { useEffect, useState } from "react";
import { ClipboardCheck, AlertTriangle, CheckCircle, ArrowRight, Database } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import Link from "next/link";

type DateStatus = {
  date: string;
  races: number;
  entries: number;
  idm: number;
  winOdds: number;
  trioOdds: number;
  results: number;
  pending: number;
  settled: number;
  canPredict: boolean;
  canSettle: boolean;
  needsData: boolean;
};

type CheckItem = {
  action: string;
  label: string;
  priority: string;
};

type StatusData = {
  today: DateStatus;
  tomorrow: DateStatus;
  latestRace: string;
  latestResult: string;
  pendingTotal: number;
  checklist: CheckItem[];
};

function DataBar({ label, value, ok }: { label: string; value: number; ok: boolean }) {
  return (
    <div className="flex items-center justify-between text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-mono", ok ? "text-green-600" : value === 0 ? "text-red-500" : "text-muted-foreground")}>
        {value > 0 ? `${value}` : "なし"} {ok ? "✓" : value === 0 ? "✗" : ""}
      </span>
    </div>
  );
}

export function OpsChecklist() {
  const [data, setData] = useState<StatusData | null>(null);

  useEffect(() => {
    fetch("/api/jrdb/status")
      .then(r => r.json())
      .then(setData)
      .catch(() => {});
  }, []);

  if (!data) return null;

  const actionLinks: Record<string, string> = {
    predict: "/paper-trade",
    settle: "/paper-trade",
    settle_all: "/paper-trade",
    import: "/settings",
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <ClipboardCheck className="h-4 w-4" />
          <CardTitle className="text-sm">運用チェックリスト</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Checklist */}
        {data.checklist.length > 0 ? (
          <div className="space-y-1.5">
            {data.checklist.map((item, i) => (
              <Link
                key={i}
                href={actionLinks[item.action] ?? "/"}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-xs transition-colors hover:bg-muted",
                  item.priority === "high" && "bg-red-50 dark:bg-red-950 text-red-700 dark:text-red-300",
                  item.priority === "medium" && "bg-yellow-50 dark:bg-yellow-950 text-yellow-700 dark:text-yellow-300",
                )}
              >
                {item.priority === "high" ? <AlertTriangle className="h-3 w-3 shrink-0" /> : <ArrowRight className="h-3 w-3 shrink-0" />}
                <span>{item.label}</span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-xs text-green-600">
            <CheckCircle className="h-4 w-4" />
            <span>全て完了。次のレース日のデータ待ち。</span>
          </div>
        )}

        {/* Data status */}
        <div className="grid grid-cols-2 gap-3 pt-2 border-t">
          {[data.today, data.tomorrow].map(d => (
            <div key={d.date}>
              <div className="text-[10px] font-medium text-muted-foreground mb-1">
                {d.date === data.today.date ? "今日" : "明日"} ({d.date.slice(5)})
              </div>
              <DataBar label="レース" value={d.races} ok={d.races > 0} />
              <DataBar label="IDM" value={d.idm} ok={d.idm > 0} />
              <DataBar label="オッズ" value={d.winOdds} ok={d.winOdds > 0} />
              <DataBar label="結果" value={d.results} ok={d.results > 0} />
              {d.pending > 0 && (
                <div className="text-[10px] text-orange-500 mt-0.5">未決済 {d.pending}件</div>
              )}
            </div>
          ))}
        </div>

        {/* Pending alert */}
        {data.pendingTotal > 0 && (
          <div className="rounded bg-orange-50 dark:bg-orange-950 px-3 py-1.5 text-[10px] text-orange-700 dark:text-orange-300">
            未決済合計: {data.pendingTotal}件 — SED/HJCをインポートして決済してください
          </div>
        )}
      </CardContent>
    </Card>
  );
}
