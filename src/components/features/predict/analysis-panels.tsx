"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PieChart,
  Pie,
  Cell,
  Legend,
  ResponsiveContainer,
} from "recharts";

// --- 折りたたみパネル ---

function CollapsiblePanel({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="rounded-md border">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 p-3 text-left text-sm font-semibold hover:bg-muted/50"
      >
        {open ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
        {title}
      </button>
      {open && <div className="border-t p-4">{children}</div>}
    </div>
  );
}

// --- 予測×オッズ歪みチャート（SVG直描画）---

type HorsePoint = {
  horseNumber: number;
  horseName: string;
  aiScore: number;
  oddsValue: string;
  odds: number;
  gateNumber?: number;
};

const oddsValueToY: Record<string, number> = {
  "A+": 5,
  A: 4,
  B: 3,
  C: 2,
  D: 1,
};

const oddsValueLabels: Record<string, string> = {
  "A+": "大幅割安",
  A: "割安",
  B: "適正",
  C: "やや割高",
  D: "割高",
};

// JRA枠番色
const GATE_BG: Record<number, string> = {
  1: "#ffffff",
  2: "#222222",
  3: "#ef4444",
  4: "#3b82f6",
  5: "#eab308",
  6: "#22c55e",
  7: "#f97316",
  8: "#ec4899",
};
const GATE_FG: Record<number, string> = {
  1: "#000000",
  2: "#ffffff",
  3: "#ffffff",
  4: "#ffffff",
  5: "#000000",
  6: "#ffffff",
  7: "#ffffff",
  8: "#ffffff",
};

export function OddsDistortionChart({ horses }: { horses: HorsePoint[] }) {
  const data = horses.map((h) => ({
    ...h,
    y: oddsValueToY[h.oddsValue] ?? 3,
  }));

  const S = 500; // 正方形
  const PAD = { top: 10, right: 10, bottom: 35, left: 45 };
  const plotW = S - PAD.left - PAD.right;
  const plotH = S - PAD.top - PAD.bottom;

  // X軸: AI偏差値
  const scores = data.map((d) => d.aiScore);
  const xMin = Math.max(30, Math.floor(Math.min(...scores) / 5) * 5 - 5);
  const xMax = Math.min(80, Math.ceil(Math.max(...scores) / 5) * 5 + 5);
  const toX = (v: number) => PAD.left + ((v - xMin) / (xMax - xMin)) * plotW;

  // Y軸: 歪み 0-6（表示は1-5）
  const toY = (v: number) => PAD.top + ((6 - v) / 6) * plotH;

  // 中心座標
  const cx = PAD.left + plotW / 2;
  const cy = PAD.top + plotH / 2;

  return (
    <CollapsiblePanel title="予測×オッズ歪み" defaultOpen>
      <div className="flex justify-center overflow-x-auto">
        <svg viewBox={`0 0 ${S} ${S}`} className="h-auto w-full max-w-[500px]">
          <defs>
            {/* 左下→右上のグラデーション（ピンク→グリーン） */}
            <linearGradient id="bg-main" x1="0" y1="1" x2="1" y2="0">
              <stop offset="0%" stopColor="#fca5a5" stopOpacity="0.45" />
              <stop offset="40%" stopColor="#fef2f2" stopOpacity="0.15" />
              <stop offset="60%" stopColor="#f0fdf4" stopOpacity="0.15" />
              <stop offset="100%" stopColor="#86efac" stopOpacity="0.45" />
            </linearGradient>
            {/* 右下もうっすらピンク */}
            <linearGradient id="bg-rb" x1="1" y1="1" x2="0" y2="0">
              <stop offset="0%" stopColor="#fca5a5" stopOpacity="0.2" />
              <stop offset="100%" stopColor="transparent" stopOpacity="0" />
            </linearGradient>
            {/* 左上もうっすらピンク */}
            <linearGradient id="bg-lt" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#fca5a5" stopOpacity="0.1" />
              <stop offset="100%" stopColor="transparent" stopOpacity="0" />
            </linearGradient>
          </defs>

          {/* 背景 */}
          <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="#fff" />
          <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="url(#bg-main)" />
          <rect x={cx} y={cy} width={plotW / 2} height={plotH / 2} fill="url(#bg-rb)" />
          <rect x={PAD.left} y={PAD.top} width={plotW / 2} height={plotH / 2} fill="url(#bg-lt)" />

          {/* 中心線（十字） */}
          <line x1={cx} y1={PAD.top} x2={cx} y2={PAD.top + plotH} stroke="#e5e7eb" strokeWidth="1" />
          <line x1={PAD.left} y1={cy} x2={PAD.left + plotW} y2={cy} stroke="#e5e7eb" strokeWidth="1" />

          {/* 枠線 */}
          <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} fill="none" stroke="#d1d5db" strokeWidth="1.5" />

          {/* 軸タイトル */}
          <text x={PAD.left + plotW / 2} y={S - 5} textAnchor="middle" fontSize="12" fill="#6b7280">
            遅 ← 予測値 → 速
          </text>
          <text
            x={14}
            y={PAD.top + plotH / 2}
            textAnchor="middle"
            fontSize="12"
            fill="#6b7280"
            transform={`rotate(-90, 14, ${PAD.top + plotH / 2})`}
          >
            割高 ← オッズ歪み → 割安
          </text>

          {/* 馬番プロット */}
          {data.map((d) => {
            const px = toX(d.aiScore);
            const py = toY(d.y);
            const gate = d.gateNumber ?? 0;
            const bg = gate > 0 ? (GATE_BG[gate] ?? "#6b7280") : "#6b7280";
            const fg = gate > 0 ? (GATE_FG[gate] ?? "#fff") : "#fff";
            const needsBorder = gate === 1 || gate === 0;
            const size = 15;

            return (
              <g key={d.horseNumber}>
                <title>
                  {d.horseNumber}. {d.horseName} (AI:{d.aiScore} 歪み:{d.oddsValue} {d.odds}倍)
                </title>
                {/* 影 */}
                <rect
                  x={px - size + 2}
                  y={py - size + 2}
                  width={size * 2}
                  height={size * 2}
                  rx={5}
                  fill="rgba(0,0,0,0.15)"
                />
                {/* 背景 */}
                <rect
                  x={px - size}
                  y={py - size}
                  width={size * 2}
                  height={size * 2}
                  rx={5}
                  fill={bg}
                  stroke={needsBorder ? "#999" : "none"}
                  strokeWidth={needsBorder ? 1.5 : 0}
                />
                {/* 馬番 */}
                <text
                  x={px}
                  y={py + 1}
                  textAnchor="middle"
                  dominantBaseline="central"
                  fontSize="14"
                  fontWeight="bold"
                  fill={fg}
                >
                  {d.horseNumber}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {/* 凡例テーブル */}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b text-muted-foreground">
              <th className="px-2 py-1 text-left">馬番</th>
              <th className="px-2 py-1 text-left">馬名</th>
              <th className="px-2 py-1 text-right">偏差値</th>
              <th className="px-2 py-1 text-center">歪み</th>
              <th className="px-2 py-1 text-right">オッズ</th>
            </tr>
          </thead>
          <tbody>
            {data
              .sort((a, b) => b.aiScore - a.aiScore)
              .map((d) => {
                const gate = d.gateNumber ?? 0;
                const bg = gate > 0 ? (GATE_BG[gate] ?? "#6b7280") : "#6b7280";
                const fg = gate > 0 ? (GATE_FG[gate] ?? "#fff") : "#fff";
                return (
                  <tr key={d.horseNumber} className="border-b">
                    <td className="px-2 py-1">
                      <span
                        className="inline-flex h-6 w-6 items-center justify-center rounded text-xs font-bold"
                        style={{
                          backgroundColor: bg,
                          color: fg,
                          border: (gate === 1 || gate === 0) ? "1px solid #999" : "none",
                        }}
                      >
                        {d.horseNumber}
                      </span>
                    </td>
                    <td className="px-2 py-1 font-medium">{d.horseName}</td>
                    <td className="px-2 py-1 text-right font-bold">{d.aiScore}</td>
                    <td className="px-2 py-1 text-center">
                      <span className={cn(
                        "rounded px-1.5 py-0.5 text-xs font-bold",
                        d.oddsValue === "A+" ? "bg-red-100 text-red-700" :
                        d.oddsValue === "A" ? "bg-orange-100 text-orange-700" :
                        d.oddsValue === "B" ? "bg-gray-100 text-gray-700" :
                        d.oddsValue === "C" ? "bg-blue-100 text-blue-700" :
                        "bg-gray-50 text-gray-400"
                      )}>
                        {d.oddsValue}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-right">{d.odds > 0 ? `${d.odds}倍` : "-"}</td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </CollapsiblePanel>
  );
}

// --- 傾向テーブル + 円グラフ ---

type TrendRow = {
  label: string;
  winRate: number;
  placeRate: number;
  count: number;
  color?: string;
};

const TREND_COLORS = [
  "#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6",
  "#8b5cf6", "#ec4899", "#14b8a6", "#64748b", "#000000",
  "#a855f7", "#06b6d4",
];

function TrendTable({
  title,
  rows,
  showPie = true,
}: {
  title: string;
  rows: TrendRow[];
  showPie?: boolean;
}) {
  const pieData = rows.map((r, i) => ({
    name: r.label,
    value: r.count,
    color: r.color ?? TREND_COLORS[i % TREND_COLORS.length],
  }));

  return (
    <CollapsiblePanel title={title}>
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-muted/50 text-xs">
                <th className="p-2 text-left">
                  {title.replace("の傾向", "")}
                </th>
                <th className="p-2 text-right">勝率</th>
                <th className="p-2 text-right">複勝率</th>
                <th className="p-2 text-right">出走</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-b">
                  <td className="p-2 font-medium">
                    <span className="flex items-center gap-2">
                      <span
                        className="inline-block h-3 w-3 rounded-sm"
                        style={{
                          backgroundColor:
                            r.color ?? TREND_COLORS[i % TREND_COLORS.length],
                        }}
                      />
                      {r.label}
                    </span>
                  </td>
                  <td
                    className={cn(
                      "p-2 text-right",
                      r.winRate >= 10 ? "font-bold text-red-500" : ""
                    )}
                  >
                    {r.winRate.toFixed(1)}%
                  </td>
                  <td
                    className={cn(
                      "p-2 text-right",
                      r.placeRate >= 30 ? "font-bold text-green-600" : ""
                    )}
                  >
                    {r.placeRate.toFixed(1)}%
                  </td>
                  <td className="p-2 text-right text-muted-foreground">
                    {r.count.toLocaleString()}回
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {showPie && pieData.length > 0 && (
          <div>
            <p className="mb-1 text-center text-xs text-muted-foreground">
              一位率
            </p>
            <ResponsiveContainer width="100%" height={200}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  outerRadius={80}
                  dataKey="value"
                  nameKey="name"
                >
                  {pieData.map((d, i) => (
                    <Cell key={i} fill={d.color} />
                  ))}
                </Pie>
                <Legend
                  wrapperStyle={{ fontSize: 10 }}
                  formatter={(value: string) => (
                    <span className="text-xs">{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </CollapsiblePanel>
  );
}

// --- 枠番テーブル ---

// 枠番テーブル用の色（1枠は薄いグレーで見やすく）
const GATE_TABLE_COLORS = [
  "#d1d5db", "#222222", "#ef4444", "#3b82f6",
  "#eab308", "#22c55e", "#f97316", "#ec4899",
];

export function GateStatsPanel({
  stats,
}: {
  stats: {
    gate_number: number;
    win_rate: number;
    place_rate: number;
    total_entries: number;
  }[];
}) {
  if (!stats || stats.length === 0) return null;

  const rows: TrendRow[] = stats.map((s) => ({
    label: `${s.gate_number}番`,
    winRate: s.win_rate,
    placeRate: s.place_rate,
    count: s.total_entries,
    color: GATE_TABLE_COLORS[(s.gate_number - 1) % GATE_TABLE_COLORS.length],
  }));

  return <TrendTable title="枠番の傾向" rows={rows} />;
}

// --- 騎手テーブル ---

export function JockeyStatsPanel({
  stats,
}: {
  stats: {
    name: string;
    win_rate: number;
    place_rate: number;
    total: number;
  }[];
}) {
  if (!stats || stats.length === 0) return null;

  const rows: TrendRow[] = stats.map((s, i) => ({
    label: s.name,
    winRate: s.win_rate,
    placeRate: s.place_rate,
    count: s.total,
    color: TREND_COLORS[i % TREND_COLORS.length],
  }));

  return <TrendTable title="騎手の傾向" rows={rows} />;
}

// --- 調教師テーブル ---

export function TrainerStatsPanel({
  stats,
}: {
  stats: {
    name: string;
    win_rate: number;
    place_rate: number;
    total: number;
  }[];
}) {
  if (!stats || stats.length === 0) return null;

  const rows: TrendRow[] = stats.map((s, i) => ({
    label: s.name,
    winRate: s.win_rate,
    placeRate: s.place_rate,
    count: s.total,
    color: TREND_COLORS[i % TREND_COLORS.length],
  }));

  return <TrendTable title="調教師の傾向" rows={rows} />;
}

// --- 性別テーブル ---

const SEX_COLORS: Record<string, string> = {
  牝: "#ef4444",
  牡: "#3b82f6",
  セ: "#22c55e",
};

export function SexStatsPanel({
  stats,
}: {
  stats: {
    sex: string;
    win_rate: number;
    place_rate: number;
    total_entries: number;
  }[];
}) {
  if (!stats || stats.length === 0) return null;

  const rows: TrendRow[] = stats.map((s) => ({
    label: `${s.sex}馬`,
    winRate: s.win_rate,
    placeRate: s.place_rate,
    count: s.total_entries,
    color: SEX_COLORS[s.sex] ?? "#9ca3af",
  }));

  return <TrendTable title="性別の傾向" rows={rows} />;
}
