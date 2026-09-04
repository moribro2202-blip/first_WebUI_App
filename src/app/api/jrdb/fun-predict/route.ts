import { NextResponse } from "next/server";
import { predictRace, type M7Prediction } from "@/lib/m7-engine";
import { getDb } from "@/lib/jrdb/db";

/**
 * 楽しく賭けるための予想API
 * M7スコアベースで複数の賭け方を提案
 */

type FunBet = {
  type: string;
  label: string;
  combination: string;
  horses: Array<{ num: number; name: string; score: number; prob: number }>;
  expectedHitRate: number;
  funLevel: number;     // 1-5 (5=最も楽しい)
  riskLevel: number;    // 1-5 (5=最もリスキー)
  description: string;
};

function generateFunBets(pred: M7Prediction): FunBet[] {
  const bets: FunBet[] = [];
  const h = pred.horses; // sorted by blendedProb desc
  if (h.length < 3) return bets;

  const top1 = h[0], top2 = h[1], top3 = h[2];
  const top4 = h[3] ?? null;
  const top5 = h[4] ?? null;

  // 1. 複勝 ◎ (most safe)
  bets.push({
    type: "fukusho",
    label: "複勝 ◎",
    combination: `${top1.horseNumber}`,
    horses: [{ num: top1.horseNumber, name: top1.horseName, score: top1.totalScore, prob: top1.blendedProb }],
    expectedHitRate: Math.min(95, top1.blendedProb * 300),
    funLevel: 2,
    riskLevel: 1,
    description: "3着以内に入れば当たり。最も堅い賭け方。",
  });

  // 2. ワイド ◎-○ (safe & fun)
  bets.push({
    type: "wide",
    label: "ワイド ◎-○",
    combination: `${Math.min(top1.horseNumber, top2.horseNumber)}-${Math.max(top1.horseNumber, top2.horseNumber)}`,
    horses: [
      { num: top1.horseNumber, name: top1.horseName, score: top1.totalScore, prob: top1.blendedProb },
      { num: top2.horseNumber, name: top2.horseName, score: top2.totalScore, prob: top2.blendedProb },
    ],
    expectedHitRate: Math.min(80, (top1.blendedProb + top2.blendedProb) * 150),
    funLevel: 3,
    riskLevel: 2,
    description: "2頭とも3着以内なら当たり。当たりやすく配当もそこそこ。",
  });

  // 3. 馬連 ◎-○
  bets.push({
    type: "umaren",
    label: "馬連 ◎-○",
    combination: `${Math.min(top1.horseNumber, top2.horseNumber)}-${Math.max(top1.horseNumber, top2.horseNumber)}`,
    horses: [
      { num: top1.horseNumber, name: top1.horseName, score: top1.totalScore, prob: top1.blendedProb },
      { num: top2.horseNumber, name: top2.horseName, score: top2.totalScore, prob: top2.blendedProb },
    ],
    expectedHitRate: Math.min(40, (top1.blendedProb * top2.blendedProb) * 800),
    funLevel: 3,
    riskLevel: 3,
    description: "1着2着の組み合わせ（順不同）。ワイドより配当高め。",
  });

  // 4. ワイド ◎-▲ (fun spread)
  bets.push({
    type: "wide",
    label: "ワイド ◎-▲",
    combination: `${Math.min(top1.horseNumber, top3.horseNumber)}-${Math.max(top1.horseNumber, top3.horseNumber)}`,
    horses: [
      { num: top1.horseNumber, name: top1.horseName, score: top1.totalScore, prob: top1.blendedProb },
      { num: top3.horseNumber, name: top3.horseName, score: top3.totalScore, prob: top3.blendedProb },
    ],
    expectedHitRate: Math.min(60, (top1.blendedProb + top3.blendedProb) * 130),
    funLevel: 3,
    riskLevel: 2,
    description: "◎と▲のワイド。○が来なくても当たる保険。",
  });

  // 5. 三連複 ◎○▲ (M7 specialty)
  const triNums = [top1.horseNumber, top2.horseNumber, top3.horseNumber].sort((a, b) => a - b);
  bets.push({
    type: "sanrenpuku",
    label: "三連複 ◎○▲",
    combination: triNums.join("-"),
    horses: [
      { num: top1.horseNumber, name: top1.horseName, score: top1.totalScore, prob: top1.blendedProb },
      { num: top2.horseNumber, name: top2.horseName, score: top2.totalScore, prob: top2.blendedProb },
      { num: top3.horseNumber, name: top3.horseName, score: top3.totalScore, prob: top3.blendedProb },
    ],
    expectedHitRate: pred.trioProb * 100,
    funLevel: 4,
    riskLevel: 4,
    description: `M7予測の本命。PredBlend=${pred.predBlend.toFixed(1)}倍。${pred.shouldBet ? "BET推奨！" : ""}`,
  });

  // 6. 三連複 ◎○▲△ 4点 (wider net)
  if (top4) {
    const nums4 = [top1, top2, top3, top4];
    const combos: string[] = [];
    for (let i = 0; i < 4; i++) {
      for (let j = i + 1; j < 4; j++) {
        for (let k = j + 1; k < 4; k++) {
          combos.push([nums4[i].horseNumber, nums4[j].horseNumber, nums4[k].horseNumber].sort((a, b) => a - b).join("-"));
        }
      }
    }
    bets.push({
      type: "sanrenpuku_4",
      label: "三連複 ◎○▲△ (4点)",
      combination: combos.join(" / "),
      horses: nums4.map(x => ({ num: x.horseNumber, name: x.horseName, score: x.totalScore, prob: x.blendedProb })),
      expectedHitRate: Math.min(50, pred.trioProb * 100 * 3.5),
      funLevel: 4,
      riskLevel: 3,
      description: "4頭BOXで4点。当たりやすさと配当のバランス◎。",
    });
  }

  // 7. 馬単 ◎→○ (thrilling)
  bets.push({
    type: "umatan",
    label: "馬単 ◎→○",
    combination: `${top1.horseNumber}→${top2.horseNumber}`,
    horses: [
      { num: top1.horseNumber, name: top1.horseName, score: top1.totalScore, prob: top1.blendedProb },
      { num: top2.horseNumber, name: top2.horseName, score: top2.totalScore, prob: top2.blendedProb },
    ],
    expectedHitRate: Math.min(20, top1.blendedProb * top2.blendedProb * 400),
    funLevel: 4,
    riskLevel: 4,
    description: "1着2着の順番まで当てる。馬連の2倍の配当。",
  });

  return bets;
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const raceId = searchParams.get("raceId");
  if (!raceId) return NextResponse.json({ error: "raceId required" }, { status: 400 });

  const pred = predictRace(raceId);
  if (!pred) return NextResponse.json({ error: "Race not found" }, { status: 404 });

  const funBets = generateFunBets(pred);

  // Get odds for each bet type
  const db = getDb();
  for (const bet of funBets) {
    if (bet.type === "sanrenpuku_4") continue;
    const oddsRow = db.prepare(
      "SELECT odds FROM odds WHERE race_id = ? AND bet_type = ? AND combination = ?"
    ).get(raceId, bet.type, bet.combination) as { odds: number } | undefined;
    if (oddsRow) {
      (bet as Record<string, unknown>)["odds"] = oddsRow.odds;
    }
  }

  return NextResponse.json({
    race: {
      raceId: pred.raceId,
      venueName: pred.venueName,
      raceNumber: pred.raceNumber,
      raceName: pred.raceName,
      distance: pred.distance,
      surface: pred.surface,
      trackCondition: pred.trackCondition,
      weather: pred.weather,
      headCount: pred.headCount,
    },
    ranking: pred.horses.map((h, i) => ({
      rank: i + 1,
      mark: i === 0 ? "◎" : i === 1 ? "○" : i === 2 ? "▲" : i === 3 ? "△" : i === 4 ? "☆" : "",
      ...h,
    })),
    predBlend: pred.predBlend,
    shouldBet: pred.shouldBet,
    trioProb: pred.trioProb,
    funBets,
  });
}
