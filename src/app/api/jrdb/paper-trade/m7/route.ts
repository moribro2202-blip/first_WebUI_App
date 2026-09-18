import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/jrdb/db";
import { predictDate } from "@/lib/m7-engine";
import type { M7Version } from "@/lib/m7-engine";

/**
 * M7ペーパートレードAPI
 * POST: 指定日のM7予測からBET対象を自動記録
 * PUT: 指定日の全レースを一括決済
 */

export async function POST(request: NextRequest) {
  try {
    const { date, amount = 10000, version = "v27" } = await request.json();
    if (!date) return NextResponse.json({ error: "date required" }, { status: 400 });
    const modelVersion = (version === "v25" ? "v25" : "v27") as M7Version;
    const betAmount = Math.max(100, Math.floor(Number(amount)));

    const db = getDb();
    const predictions = predictDate(date, modelVersion);
    const bets = predictions.filter(p => p.shouldBet);

    // Check if already recorded for this version
    const existing = db.prepare(
      "SELECT COUNT(*) as cnt FROM paper_trades WHERE race_date = ? AND bet_type = 'sanrenpuku' AND ai_score_json LIKE ?"
    ).get(date, `%"version":"${modelVersion}"%`) as { cnt: number };
    if (existing.cnt > 0) {
      return NextResponse.json({ error: `この日は${modelVersion}で既に記録済みです`, existing: existing.cnt }, { status: 409 });
    }

    const stmt = db.prepare(`
      INSERT INTO paper_trades (race_id, race_date, bet_type, combination, amount, odds, ev, ai_score_json, result)
      VALUES (?, ?, 'sanrenpuku', ?, ?, ?, ?, ?, 'pending')
    `);

    let count = 0;
    for (const pred of bets) {
      // Get trio odds for this combination
      const trioRow = db.prepare(
        "SELECT odds FROM odds WHERE race_id = ? AND bet_type = 'sanrenpuku' AND combination = ?"
      ).get(pred.raceId, pred.combination) as { odds: number } | undefined;
      const trioOdds = trioRow?.odds ?? null;

      const scoreJson = JSON.stringify({
        model: "M7",
        version: modelVersion,
        predBlend: pred.predBlend,
        trioProb: pred.trioProb,
        top3Scores: pred.horses.slice(0, 3).map(h => ({
          num: h.horseNumber, name: h.horseName, idm: h.idm,
          score: h.totalScore, blend: h.blendedProb,
        })),
      });

      stmt.run(
        pred.raceId, date, pred.combination,
        betAmount,
        trioOdds && trioOdds > 0 ? trioOdds : null,
        pred.trioProb,
        scoreJson,
      );
      count++;
    }

    return NextResponse.json({
      date,
      recorded: count,
      total: predictions.length,
      skipped: predictions.length - bets.length,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "記録失敗" },
      { status: 500 }
    );
  }
}

export async function PUT(request: NextRequest) {
  try {
    const { date } = await request.json();
    if (!date) return NextResponse.json({ error: "date required" }, { status: 400 });

    const db = getDb();

    // Get all pending trades for this date
    const pending = db.prepare(
      "SELECT id, race_id, combination, amount, odds FROM paper_trades WHERE race_date = ? AND result = 'pending'"
    ).all(date) as Array<{
      id: number; race_id: string; combination: string; amount: number; odds: number;
    }>;

    if (pending.length === 0) {
      return NextResponse.json({ settled: 0, message: "未決済の取引なし" });
    }

    const update = db.prepare(
      "UPDATE paper_trades SET result = ?, payout = ?, settled_at = datetime('now') WHERE id = ?"
    );

    let settled = 0; let hits = 0; let totalPayout = 0;
    for (const trade of pending) {
      const results = db.prepare(
        "SELECT horse_number FROM results WHERE race_id = ? AND finish_position <= 3 ORDER BY finish_position"
      ).all(trade.race_id) as Array<{ horse_number: number }>;

      if (results.length < 3) {
        // No result data yet
        continue;
      }

      const actualTop3 = results.map(r => r.horse_number).sort((a, b) => a - b).join("-");
      const hit = trade.combination === actualTop3;

      // Use HJC confirmed odds if available, fall back to OT odds
      let finalOdds = trade.odds;
      if (hit) {
        const hjcRow = db.prepare(
          "SELECT odds FROM odds WHERE race_id = ? AND bet_type = 'sanrenpuku_hjc' AND combination = ?"
        ).get(trade.race_id, trade.combination) as { odds: number } | undefined;
        if (hjcRow) finalOdds = hjcRow.odds;
      }

      const payout = hit && finalOdds ? trade.amount * finalOdds : 0;

      // Update odds to confirmed value if changed
      if (hit && finalOdds !== trade.odds) {
        db.prepare("UPDATE paper_trades SET odds = ? WHERE id = ?").run(finalOdds, trade.id);
      }

      update.run(hit ? "hit" : "miss", payout, trade.id);
      settled++;
      if (hit) { hits++; totalPayout += payout; }
    }

    return NextResponse.json({
      date, settled, hits, totalPayout,
      invested: pending.slice(0, settled).reduce((s, t) => s + t.amount, 0),
      rr: settled > 0 ? ((totalPayout / pending.slice(0, settled).reduce((s, t) => s + t.amount, 0)) * 100).toFixed(1) + "%" : "N/A",
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "決済失敗" },
      { status: 500 }
    );
  }
}

export async function DELETE(request: NextRequest) {
  try {
    const { date, version } = await request.json();
    if (!date) return NextResponse.json({ error: "date required" }, { status: 400 });

    const db = getDb();
    const likePattern = version ? `%"version":"${version}"%` : '%M7%';
    const result = db.prepare(
      "DELETE FROM paper_trades WHERE race_date = ? AND ai_score_json LIKE ?"
    ).run(date, likePattern);

    return NextResponse.json({ date, deleted: result.changes });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "削除失敗" },
      { status: 500 }
    );
  }
}
