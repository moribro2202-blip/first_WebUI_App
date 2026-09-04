"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import type { HorseEntry } from "@/types";

type EntriesFormProps = {
  entries: HorseEntry[];
  onChange: (entries: HorseEntry[]) => void;
};

const emptyEntry = (): HorseEntry => ({
  number: 0,
  name: "",
  jockey: "",
  weight: 56,
  odds: 0,
  popularity: 0,
  age: "",
  trainer: "",
});

// 人気順で背景色を付ける
function getPopularityColor(popularity: number): string {
  if (popularity === 1) return "bg-red-50 border-red-200 dark:bg-red-950/30 dark:border-red-800";
  if (popularity === 2) return "bg-orange-50 border-orange-200 dark:bg-orange-950/30 dark:border-orange-800";
  if (popularity === 3) return "bg-yellow-50 border-yellow-200 dark:bg-yellow-950/30 dark:border-yellow-800";
  if (popularity >= 4 && popularity <= 6) return "bg-blue-50 border-blue-200 dark:bg-blue-950/20 dark:border-blue-800";
  if (popularity >= 7 && popularity <= 9) return "bg-gray-50 border-gray-200 dark:bg-gray-900/30 dark:border-gray-700";
  if (popularity >= 10) return "bg-gray-100 border-gray-300 dark:bg-gray-900/50 dark:border-gray-600";
  return "";
}

export function EntriesForm({ entries, onChange }: EntriesFormProps) {
  const updateEntry = (index: number, patch: Partial<HorseEntry>) => {
    const next = entries.map((e, i) => (i === index ? { ...e, ...patch } : e));
    onChange(next);
  };

  const addEntry = () => {
    onChange([...entries, { ...emptyEntry(), number: entries.length + 1 }]);
  };

  const removeEntry = (index: number) => {
    onChange(entries.filter((_, i) => i !== index));
  };

  const addBulkEntries = (count: number) => {
    const newEntries = Array.from({ length: count }, (_, i) => ({
      ...emptyEntry(),
      number: i + 1,
    }));
    onChange(newEntries);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Label className="text-base font-semibold">出馬表（{entries.length}頭）</Label>
        <div className="flex gap-2">
          {[8, 12, 16, 18].map((n) => (
            <Button
              key={n}
              variant="outline"
              size="sm"
              onClick={() => addBulkEntries(n)}
            >
              {n}頭
            </Button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {entries.map((entry, i) => (
          <div
            key={i}
            className={cn(
              "grid grid-cols-[4rem_1fr_1fr_4rem_5rem_3.5rem_4rem_1fr_2rem] items-end gap-2 rounded-md border p-3",
              entry.popularity > 0 && getPopularityColor(entry.popularity)
            )}
          >
            {/* 馬番 */}
            <div className="space-y-1">
              <Label className="text-xs">馬番</Label>
              <Input
                type="number"
                value={entry.number || ""}
                onChange={(e) => updateEntry(i, { number: Number(e.target.value) })}
                className="h-8 text-center text-sm"
              />
            </div>
            {/* 馬名 */}
            <div className="space-y-1">
              <Label className="text-xs">馬名</Label>
              <Input
                value={entry.name}
                onChange={(e) => updateEntry(i, { name: e.target.value })}
                placeholder="馬名"
                className="h-8 text-sm"
              />
            </div>
            {/* 騎手 */}
            <div className="space-y-1">
              <Label className="text-xs">騎手</Label>
              <Input
                value={entry.jockey}
                onChange={(e) => updateEntry(i, { jockey: e.target.value })}
                placeholder="騎手"
                className="h-8 text-sm"
              />
            </div>
            {/* 斤量 */}
            <div className="space-y-1">
              <Label className="text-xs">斤量</Label>
              <Input
                type="number"
                value={entry.weight || ""}
                onChange={(e) => updateEntry(i, { weight: Number(e.target.value) })}
                className="h-8 text-sm"
              />
            </div>
            {/* オッズ */}
            <div className="space-y-1">
              <Label className="text-xs">オッズ</Label>
              <Input
                type="number"
                step="0.1"
                value={entry.odds || ""}
                onChange={(e) => updateEntry(i, { odds: Number(e.target.value) })}
                className="h-8 text-sm"
              />
            </div>
            {/* 人気 */}
            <div className="space-y-1">
              <Label className="text-xs">人気</Label>
              <Input
                type="number"
                value={entry.popularity || ""}
                onChange={(e) => updateEntry(i, { popularity: Number(e.target.value) })}
                className="h-8 text-sm"
              />
            </div>
            {/* 年齢 */}
            <div className="space-y-1">
              <Label className="text-xs">年齢</Label>
              <Input
                value={entry.age}
                onChange={(e) => updateEntry(i, { age: e.target.value })}
                placeholder="牡4"
                className="h-8 text-sm"
              />
            </div>
            {/* 調教師 */}
            <div className="space-y-1">
              <Label className="text-xs">調教師</Label>
              <Input
                value={entry.trainer}
                onChange={(e) => updateEntry(i, { trainer: e.target.value })}
                placeholder="調教師"
                className="h-8 text-sm"
              />
            </div>
            {/* 削除 */}
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-destructive"
              onClick={() => removeEntry(i)}
              aria-label="削除"
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        ))}
      </div>

      <Button variant="outline" onClick={addEntry} className="w-full">
        <Plus className="mr-2 h-4 w-4" />
        馬を追加
      </Button>
    </div>
  );
}
