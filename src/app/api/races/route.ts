import { NextRequest, NextResponse } from "next/server";
import type { RaceInfo, HorseEntry, RaceType } from "@/types";

// netkeiba等からのデータ取得のプロキシAPI
// Phase1: 手動入力のフォールバックあり、将来的にスクレイピングorAPI連携

type NetkeibaRace = {
  race_id: string;
  race_name: string;
  race_date: string;
  venue: string;
  race_number: number;
  distance: number;
  surface: string;
  condition: string;
  head_count: number;
  start_time: string;
  entries: {
    number: number;
    name: string;
    jockey: string;
    weight: number;
    odds: number;
    popularity: number;
    age: string;
    trainer: string;
  }[];
};

async function fetchRaceFromNetkeiba(raceId: string): Promise<RaceInfo | null> {
  // TODO: 実際のAPI連携を実装
  // 現段階ではサンプルデータを返す（開発用）
  // 将来的にnetkeiba APIまたはスクレイピングで取得

  // サンプルデータ（新潟記念の例 - 参考資料⑥より）
  if (raceId === "sample") {
    return {
      id: "202604030408",
      date: "2026/08/30",
      venue: "新潟",
      raceNumber: 8,
      name: "新潟記念",
      type: "central" as RaceType,
      distance: 2000,
      surface: "芝",
      condition: "稍重",
      headCount: 11,
      startTime: "15:45",
      entries: [
        { number: 1, name: "ボーンディスウェイ", jockey: "丸山元気", weight: 56, odds: 58.1, popularity: 11, age: "牡4", trainer: "武井亮" },
        { number: 2, name: "サヴォーナ", jockey: "池添謙一", weight: 57, odds: 28.0, popularity: 8, age: "牡5", trainer: "中竹和也" },
        { number: 3, name: "ロデオドライブ", jockey: "C.ルメール", weight: 54, odds: 4.2, popularity: 3, age: "牝4", trainer: "辻哲英" },
        { number: 4, name: "ドゥレッツァ", jockey: "田辺裕信", weight: 58, odds: 8.6, popularity: 4, age: "牡5", trainer: "尾関知人" },
        { number: 5, name: "ゾロアストロ", jockey: "岩田望来", weight: 57, odds: 3.5, popularity: 1, age: "牡4", trainer: "宮田敬介" },
        { number: 6, name: "チェルヴィニア", jockey: "津村明秀", weight: 54, odds: 12.8, popularity: 6, age: "牝4", trainer: "木村哲也" },
        { number: 7, name: "ジュンブロッサム", jockey: "杉原誠人", weight: 57, odds: 41.7, popularity: 10, age: "牡5", trainer: "友道康夫" },
        { number: 8, name: "ダノンシーマ", jockey: "川田将雅", weight: 56, odds: 3.6, popularity: 2, age: "牡4", trainer: "中内田充正" },
        { number: 9, name: "アーバンシック", jockey: "三浦皇成", weight: 57, odds: 14.2, popularity: 7, age: "牡4", trainer: "牧光二" },
        { number: 10, name: "バレエマスター", jockey: "菊沢一樹", weight: 55, odds: 28.8, popularity: 9, age: "セ6", trainer: "梅田智之" },
        { number: 11, name: "ステレンボッシュ", jockey: "戸崎圭太", weight: 54, odds: 12.1, popularity: 5, age: "牝4", trainer: "国枝栄" },
      ],
    };
  }

  return null;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const raceId = searchParams.get("raceId");

  if (!raceId) {
    return NextResponse.json({ error: "raceId is required" }, { status: 400 });
  }

  const raceInfo = await fetchRaceFromNetkeiba(raceId);

  if (!raceInfo) {
    return NextResponse.json({ error: "Race not found" }, { status: 404 });
  }

  return NextResponse.json({ raceInfo });
}
