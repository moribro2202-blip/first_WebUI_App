import { z } from "zod/v4";

export const horseEntrySchema = z.object({
  number: z.number().min(1, "馬番を入力"),
  name: z.string().min(1, "馬名を入力"),
  jockey: z.string().min(1, "騎手を入力"),
  weight: z.number().min(40).max(70),
  odds: z.number().min(1),
  popularity: z.number().min(1),
  age: z.string().min(1, "年齢を入力"),
  trainer: z.string().min(1, "調教師を入力"),
});

export const raceFormSchema = z.object({
  venue: z.string().min(1, "開催場を選択"),
  raceNumber: z.number().min(1).max(12),
  name: z.string().min(1, "レース名を入力"),
  date: z.string().min(1, "日付を入力"),
  startTime: z.string().min(1, "発走時刻を入力"),
  distance: z.number().min(800).max(4000),
  surface: z.enum(["芝", "ダート"]),
  condition: z.enum(["良", "稍重", "重", "不良"]),
  type: z.enum(["central", "local"]),
});

export type RaceFormValues = z.infer<typeof raceFormSchema>;
export type HorseEntryValues = z.infer<typeof horseEntrySchema>;
