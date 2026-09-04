"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { RaceFormValues } from "@/lib/validations/race";

const VENUES_CENTRAL = [
  "東京", "中山", "阪神", "京都", "中京", "小倉", "札幌", "函館", "福島", "新潟",
];
const VENUES_LOCAL = [
  "大井", "川崎", "船橋", "浦和", "門別", "園田", "姫路", "高知", "佐賀", "名古屋", "笠松", "金沢", "盛岡", "水沢",
];

type RaceFormProps = {
  values: RaceFormValues;
  onChange: (values: RaceFormValues) => void;
};

export function RaceForm({ values, onChange }: RaceFormProps) {
  const venues = values.type === "central" ? VENUES_CENTRAL : VENUES_LOCAL;

  const update = (patch: Partial<RaceFormValues>) => {
    onChange({ ...values, ...patch });
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {/* 中央/地方 */}
      <div className="space-y-2">
        <Label>中央/地方</Label>
        <Select
          value={values.type}
          onValueChange={(v) => update({ type: v as "central" | "local", venue: "" })}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="central">中央競馬</SelectItem>
            <SelectItem value="local">地方競馬</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* 開催場 */}
      <div className="space-y-2">
        <Label>開催場</Label>
        <Select value={values.venue} onValueChange={(v) => update({ venue: v ?? "" })}>
          <SelectTrigger><SelectValue placeholder="選択" /></SelectTrigger>
          <SelectContent>
            {venues.map((v) => (
              <SelectItem key={v} value={v}>{v}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* レース番号 */}
      <div className="space-y-2">
        <Label>レース番号</Label>
        <Select
          value={String(values.raceNumber)}
          onValueChange={(v) => update({ raceNumber: Number(v) })}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
              <SelectItem key={n} value={String(n)}>{n}R</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* レース名 */}
      <div className="space-y-2">
        <Label>レース名</Label>
        <Input
          value={values.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="例: 新潟記念"
        />
      </div>

      {/* 日付 */}
      <div className="space-y-2">
        <Label>日付</Label>
        <Input
          type="date"
          value={values.date}
          onChange={(e) => update({ date: e.target.value })}
        />
      </div>

      {/* 発走時刻 */}
      <div className="space-y-2">
        <Label>発走時刻</Label>
        <Input
          type="time"
          value={values.startTime}
          onChange={(e) => update({ startTime: e.target.value })}
        />
      </div>

      {/* 距離 */}
      <div className="space-y-2">
        <Label>距離 (m)</Label>
        <Input
          type="number"
          value={values.distance || ""}
          onChange={(e) => update({ distance: Number(e.target.value) })}
          placeholder="2000"
        />
      </div>

      {/* 馬場 */}
      <div className="space-y-2">
        <Label>馬場</Label>
        <Select
          value={values.surface}
          onValueChange={(v) => update({ surface: v as "芝" | "ダート" })}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="芝">芝</SelectItem>
            <SelectItem value="ダート">ダート</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* 馬場状態 */}
      <div className="space-y-2">
        <Label>馬場状態</Label>
        <Select
          value={values.condition}
          onValueChange={(v) => update({ condition: v as "良" | "稍重" | "重" | "不良" })}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="良">良</SelectItem>
            <SelectItem value="稍重">稍重</SelectItem>
            <SelectItem value="重">重</SelectItem>
            <SelectItem value="不良">不良</SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
