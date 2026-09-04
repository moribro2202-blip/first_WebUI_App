import { NextResponse } from "next/server";
import { predictRace } from "@/lib/m7-engine";
import { getDb } from "@/lib/jrdb/db";

/**
 * レース予想API
 * M7スコアベースで複数の賭け方を提案
 * 回収率はPredBlend<=8フィルタでの6年間シミュレーション実績値
 */

type FunBet = {
  type: string;
  label: string;
  combination: string;
  horses: Array<{ num: number; name: string }>;
  hitRate: number;       // シミュレーション実績的中率
  returnRate: number;    // シミュレーション実績回収率
  stars: number;         // おすすめ度 1-3
  description: string;
  odds?: number;
};

function generateFunBets(pred: ReturnType<typeof predictRace>): FunBet[] {
  if (!pred) return [];
  const bets: FunBet[] = [];
  const h = pred.horses;
  if (h.length < 3) return bets;

  const top1 = h[0], top2 = h[1], top3 = h[2];
  const top4 = h[3] ?? null;
  const mk = (n: number, name: string) => ({ num: n, name });

  // Data from PredBlend<=8 simulation (6 years, 2021-2026)
  // Sort by return rate desc

  // 1. 三連複 ◎○▲ - RR 116.6%, HR 12.9%
  const triNums = [top1.horseNumber, top2.horseNumber, top3.horseNumber].sort((a, b) => a - b);
  bets.push({
    type: "sanrenpuku", label: "三連複 ◎○▲",
    combination: triNums.join("-"),
    horses: [mk(top1.horseNumber, top1.horseName), mk(top2.horseNumber, top2.horseName), mk(top3.horseNumber, top3.horseName)],
    hitRate: 12.9, returnRate: 116.6, stars: 3,
    description: "M7の本命。6年通算で唯一の確実なプラス券種。",
  });

  // 2. 馬単 ◎→○ - RR 101.8%, HR 12.1%
  bets.push({
    type: "umatan", label: "馬単 ◎→○",
    combination: `${top1.horseNumber}-${top2.horseNumber}`,
    horses: [mk(top1.horseNumber, top1.horseName), mk(top2.horseNumber, top2.horseName)],
    hitRate: 12.1, returnRate: 101.8, stars: 3,
    description: "1着2着の順番まで当てる。意外にもプラス圏。",
  });

  // 3. 三連単 ◎→○→▲ - RR 97.7%, HR 3.3%
  bets.push({
    type: "sanrentan", label: "三連単 ◎→○→▲",
    combination: `${top1.horseNumber}-${top2.horseNumber}-${top3.horseNumber}`,
    horses: [mk(top1.horseNumber, top1.horseName), mk(top2.horseNumber, top2.horseName), mk(top3.horseNumber, top3.horseName)],
    hitRate: 3.3, returnRate: 97.7, stars: 2,
    description: "高配当狙い。当たれば大きいがほぼトントン。",
  });

  // 4. ワイド ◎○ - RR 96.5%, HR 44.3%
  bets.push({
    type: "wide", label: "ワイド ◎-○",
    combination: [top1.horseNumber, top2.horseNumber].sort((a, b) => a - b).join("-"),
    horses: [mk(top1.horseNumber, top1.horseName), mk(top2.horseNumber, top2.horseName)],
    hitRate: 44.3, returnRate: 96.5, stars: 2,
    description: "2頭とも3着以内で当たり。楽しくてほぼトントン。",
  });

  // 5. 馬連 ◎○ - RR 96.1%, HR 18.6%
  bets.push({
    type: "umaren", label: "馬連 ◎-○",
    combination: [top1.horseNumber, top2.horseNumber].sort((a, b) => a - b).join("-"),
    horses: [mk(top1.horseNumber, top1.horseName), mk(top2.horseNumber, top2.horseName)],
    hitRate: 18.6, returnRate: 96.1, stars: 2,
    description: "1着2着の組み合わせ（順不同）。バランス型。",
  });

  // 6. 複勝 ◎ - RR 94.5%, HR 72.3%
  bets.push({
    type: "place", label: "複勝 ◎",
    combination: `${top1.horseNumber}`,
    horses: [mk(top1.horseNumber, top1.horseName)],
    hitRate: 72.3, returnRate: 94.5, stars: 1,
    description: "3着以内で当たり。一番当たるが配当低め。",
  });

  // 7. 三連複 BOX4点 - RR 92.2%, HR 6.8%
  if (top4) {
    const nums4 = [top1, top2, top3, top4];
    const combos: string[] = [];
    for (let i = 0; i < 4; i++)
      for (let j = i + 1; j < 4; j++)
        for (let k = j + 1; k < 4; k++)
          combos.push([nums4[i].horseNumber, nums4[j].horseNumber, nums4[k].horseNumber].sort((a, b) => a - b).join("-"));
    bets.push({
      type: "sanrenpuku", label: "三連複 BOX4点",
      combination: combos.join(" / "),
      horses: nums4.map(x => mk(x.horseNumber, x.horseName)),
      hitRate: 6.8, returnRate: 92.2, stars: 1,
      description: "4頭BOXで4点。当たりやすいが投資額も4倍。",
    });
  }

  // 8. 単勝 ◎ - RR 90.4%, HR 34.5%
  bets.push({
    type: "win", label: "単勝 ◎",
    combination: `${top1.horseNumber}`,
    horses: [mk(top1.horseNumber, top1.horseName)],
    hitRate: 34.5, returnRate: 90.4, stars: 1,
    description: "1着のみ。シンプルだがやや負ける。",
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

  const db = getDb();

  // Get odds for each bet
  for (const bet of funBets) {
    if (bet.combination.includes(" / ")) continue; // skip multi-combo
    const oddsRow = db.prepare(
      "SELECT odds FROM odds WHERE race_id = ? AND bet_type = ? AND combination = ?"
    ).get(raceId, bet.type, bet.combination) as { odds: number } | undefined;
    if (oddsRow) bet.odds = oddsRow.odds;
  }

  // Get win odds for ranking
  const winOddsRows = db.prepare(
    "SELECT combination, odds FROM odds WHERE race_id = ? AND bet_type = 'win'"
  ).all(raceId) as Array<{ combination: string; odds: number }>;
  const winOddsMap = new Map<number, number>();
  for (const r of winOddsRows) winOddsMap.set(parseInt(r.combination), r.odds);

  return NextResponse.json({
    race: {
      raceId: pred.raceId, venueName: pred.venueName, raceNumber: pred.raceNumber,
      raceName: pred.raceName, grade: pred.grade, distance: pred.distance, surface: pred.surface,
      trackCondition: pred.trackCondition, weather: pred.weather, headCount: pred.headCount,
    },
    ranking: pred.horses.map((h, i) => ({
      rank: i + 1,
      mark: i === 0 ? "◎" : i === 1 ? "○" : i === 2 ? "▲" : i === 3 ? "△" : i === 4 ? "☆" : "",
      ...h,
      winOdds: winOddsMap.get(h.horseNumber) ?? null,
    })),
    predBlend: pred.predBlend,
    shouldBet: pred.shouldBet,
    trioProb: pred.trioProb,
    funBets,
    comment: generateComment(pred),
  });
}

function generateComment(pred: ReturnType<typeof predictRace>): string {
  if (!pred) return "";
  const h = pred.horses;
  if (h.length < 3) return "";
  const top1 = h[0], top2 = h[1], top3 = h[2];
  const gap12 = top1.blendedProb - top2.blendedProb;
  const gap23 = top2.blendedProb - top3.blendedProb;
  const top1pct = (top1.blendedProb * 100).toFixed(0);
  const top2pct = (top2.blendedProb * 100).toFixed(0);

  const parts: string[] = [];

  // 本命の強さ
  if (top1.blendedProb >= 0.40) {
    parts.push(`${top1.horseName}が抜けた存在（${top1pct}%）。逆らいにくい一戦。`);
  } else if (top1.blendedProb >= 0.30) {
    parts.push(`${top1.horseName}が中心（${top1pct}%）だが、${top2.horseName}（${top2pct}%）も侮れない。`);
  } else if (gap12 < 0.03) {
    parts.push(`${top1.horseName}と${top2.horseName}が拮抗（${top1pct}% vs ${top2pct}%）。力差はほぼなし。`);
  } else {
    parts.push(`${top1.horseName}がやや優勢（${top1pct}%）。混戦模様。`);
  }

  // 脚質コメント
  const styles = h.slice(0, 5).map(x => x.runStyle).filter(Boolean);
  const escapeCount = styles.filter(s => s === '逃げ').length;
  const oiCount = styles.filter(s => s === '追込').length;
  if (escapeCount >= 2) {
    parts.push("逃げ馬が複数いてペースが速くなりそう。差し馬に注目。");
  } else if (escapeCount === 0 && oiCount >= 2) {
    parts.push("逃げ馬不在でスローペースの可能性。先行馬有利か。");
  }

  // IDMコメント
  if (top1.idm >= 60) {
    parts.push(`${top1.horseName}のIDM ${top1.idm.toFixed(0)}は高水準。実力上位。`);
  }
  if (h.length >= 4 && h[3].idm > 0 && top1.idm - h[3].idm < 5) {
    parts.push("上位の実力差が小さく波乱の余地あり。");
  }

  // PredBlend
  if (pred.predBlend <= 4) {
    parts.push("堅い決着が見込まれるレース。三連複◎○▲の的中率が高い。");
  } else if (pred.predBlend >= 10) {
    parts.push("混戦で予測が難しいレース。手広く買うか見送りが無難。");
  }

  return parts.join("");
}
