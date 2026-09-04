"use client";

import { useState } from "react";
import { Database, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { HorseEntry } from "@/types";
import type { RaceFormValues } from "@/lib/validations/race";

type JrdbRace = {
  race_id: string;
  race_date: string;
  venue_code: string;
  venue_name: string;
  race_number: number;
  race_name: string | null;
  distance: number;
  surface: string;
  start_time: string | null;
  course_direction: string | null;
};

type JrdbEntry = {
  horse_number: number;
  horse_name: string;
  jockey_name: string;
  trainer_name: string;
  carried_weight: number;
  horse_weight: number | null;
  horse_weight_diff: number | null;
  age: string | null;
  sex: string | null;
  odds_win: number | null;
  popularity: number | null;
};

type JrdbLoaderProps = {
  onLoad: (
    raceForm: Partial<RaceFormValues>,
    entries: HorseEntry[],
    jrdbRaceId: string
  ) => void;
};

export function JrdbLoader({ onLoad }: JrdbLoaderProps) {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [races, setRaces] = useState<JrdbRace[]>([]);
  const [selectedRaceId, setSelectedRaceId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const searchRaces = async () => {
    setLoading(true);
    setError(null);
    setRaces([]);
    setSelectedRaceId("");

    try {
      const res = await fetch(`/api/jrdb/races?date=${date}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);
      if (data.races.length === 0) {
        setError("この日のレースデータが見つかりません");
        return;
      }
      setRaces(data.races);
    } catch (e) {
      setError(e instanceof Error ? e.message : "検索に失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const loadRace = async () => {
    if (!selectedRaceId) return;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`/api/jrdb/races/${selectedRaceId}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error);

      const race: JrdbRace = data.race;
      const jrdbEntries: JrdbEntry[] = data.entries;

      const raceForm: Partial<RaceFormValues> = {
        venue: race.venue_name,
        raceNumber: race.race_number,
        name: race.race_name || `${race.venue_name}${race.race_number}R`,
        date: race.race_date,
        startTime: race.start_time || "",
        distance: race.distance,
        surface: race.surface as "芝" | "ダート",
        type: "central",
      };

      const entries: HorseEntry[] = jrdbEntries.map((e) => ({
        number: e.horse_number,
        name: e.horse_name,
        jockey: e.jockey_name || "",
        weight: e.carried_weight || 56,
        odds: e.odds_win || 0,
        popularity: e.popularity || 0,
        age: e.age || "",
        trainer: e.trainer_name || "",
      }));

      onLoad(raceForm, entries, selectedRaceId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "読み込みに失敗しました");
    } finally {
      setLoading(false);
    }
  };

  const selectedRace = races.find((r) => r.race_id === selectedRaceId);

  return (
    <div className="space-y-3 rounded-md border border-dashed border-primary/30 bg-primary/5 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Database className="h-4 w-4" />
        JRDBから自動入力
      </div>

      <div className="flex items-end gap-2">
        <div className="space-y-1">
          <Label className="text-xs">日付</Label>
          <Input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="h-8 w-40 text-sm"
          />
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={searchRaces}
          disabled={loading}
          className="h-8"
        >
          {loading ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Search className="mr-1 h-3 w-3" />
          )}
          検索
        </Button>
      </div>

      {races.length > 0 && (
        <div className="flex items-end gap-2">
          <div className="flex-1 space-y-1">
            <Label className="text-xs">レース選択</Label>
            <Select value={selectedRaceId} onValueChange={(v) => setSelectedRaceId(v ?? "")}>
              <SelectTrigger className="h-8 text-sm">
                <SelectValue placeholder="レースを選択" />
              </SelectTrigger>
              <SelectContent>
                {races.map((r) => (
                  <SelectItem key={r.race_id} value={r.race_id}>
                    {r.venue_name} {r.race_number}R {r.surface}{r.distance}m
                    {r.race_name ? ` ${r.race_name}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button
            size="sm"
            onClick={loadRace}
            disabled={!selectedRaceId || loading}
            className="h-8"
          >
            {loading ? (
              <Loader2 className="mr-1 h-3 w-3 animate-spin" />
            ) : (
              <Database className="mr-1 h-3 w-3" />
            )}
            読み込み
          </Button>
        </div>
      )}

      {selectedRace && (
        <p className="text-xs text-muted-foreground">
          {selectedRace.venue_name} {selectedRace.race_number}R{" "}
          {selectedRace.surface}{selectedRace.distance}m{" "}
          {selectedRace.start_time || ""}
        </p>
      )}

      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
    </div>
  );
}
