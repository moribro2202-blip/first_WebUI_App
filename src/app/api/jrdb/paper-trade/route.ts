import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/jrdb/db";

/**
 * ペーパートレードAPI
 * POST: 予想買い目を記録
 * GET: 成績集計
 * PUT: レース結果で決済
 */

export async function POST(request: NextRequest) {
  try {
    const { raceId, raceDate, bets, aiScores } = await request.json();
    const db = getDb();

    const stmt = db.prepare(`
      INSERT INTO paper_trades (race_id, race_date, bet_type, combination, amount, odds, ev, ai_score_json)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);

    let count = 0;
    for (const bet of bets) {
      stmt.run(
        raceId, raceDate, bet.betType, bet.combination,
        bet.amount, bet.odds, bet.ev ?? null,
        aiScores ? JSON.stringify(aiScores) : null
      );
      count++;
    }

    return NextResponse.json({ recorded: count });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "記録失敗" },
      { status: 500 }
    );
  }
}

export async function GET() {
  try {
    const db = getDb();

    // 全体成績
    const total = db.prepare(`
      SELECT
        COUNT(*) as total_bets,
        SUM(amount) as total_invested,
        SUM(payout) as total_payout,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as misses,
        SUM(CASE WHEN result='pending' THEN 1 ELSE 0 END) as pending
      FROM paper_trades
    `).get() as {
      total_bets: number; total_invested: number; total_payout: number;
      hits: number; misses: number; pending: number;
    };

    // 券種別
    const byType = db.prepare(`
      SELECT bet_type,
        COUNT(*) as count,
        SUM(amount) as invested,
        SUM(payout) as payout,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits
      FROM paper_trades WHERE result != 'pending'
      GROUP BY bet_type
    `).all();

    // 月別
    const byMonth = db.prepare(`
      SELECT substr(race_date, 1, 7) as month,
        SUM(amount) as invested,
        SUM(payout) as payout,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        COUNT(*) as count
      FROM paper_trades WHERE result != 'pending'
      GROUP BY month ORDER BY month
    `).all();

    // 直近の取引（レース名付き）
    const recent = db.prepare(`
      SELECT pt.*, r.venue_name, r.race_number, r.race_name, r.surface, r.distance, r.grade
      FROM paper_trades pt
      LEFT JOIN races r ON pt.race_id = r.race_id
      ORDER BY pt.race_date DESC, pt.race_id DESC LIMIT 200
    `).all();

    return NextResponse.json({
      total,
      byType,
      byMonth,
      recent,
      recoveryRate: total.total_invested > 0
        ? Math.round((total.total_payout / total.total_invested) * 1000) / 10
        : 0,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取得失敗" },
      { status: 500 }
    );
  }
}

// PUT: レース結果で決済
export async function PUT(request: NextRequest) {
  try {
    const { raceId } = await request.json();
    const db = getDb();

    // そのレースの着順を取得
    const results = db.prepare(`
      SELECT horse_number, finish_position FROM results
      WHERE race_id = ? AND finish_position IS NOT NULL
      ORDER BY finish_position
    `).all(raceId) as { horse_number: number; finish_position: number }[];

    if (results.length === 0) {
      return NextResponse.json({ error: "結果データなし" }, { status: 404 });
    }

    const top3 = results.filter(r => r.finish_position <= 3).map(r => r.horse_number);

    // 未決済の買い目を取得
    const pending = db.prepare(`
      SELECT id, bet_type, combination, amount, odds
      FROM paper_trades WHERE race_id = ? AND result = 'pending'
    `).all(raceId) as {
      id: number; bet_type: string; combination: string; amount: number; odds: number;
    }[];

    let settled = 0;
    const update = db.prepare(`
      UPDATE paper_trades SET result = ?, payout = ?, settled_at = datetime('now') WHERE id = ?
    `);

    for (const trade of pending) {
      const parts = trade.combination.split("-").map(Number);
      let hit = false;

      switch (trade.bet_type) {
        case "tansho": hit = parts[0] === top3[0]; break;
        case "fukusho": hit = top3.includes(parts[0]); break;
        case "umaren": hit = top3.length >= 2 && new Set(parts).size === new Set([...parts, ...top3.slice(0,2)]).size - 0 && parts.every(p => top3.slice(0,2).includes(p)); break;
        case "wide": hit = parts.every(p => top3.includes(p)); break;
        case "umatan": hit = parts[0] === top3[0] && parts[1] === top3[1]; break;
        case "sanrenpuku": hit = top3.length >= 3 && parts.sort().join("-") === [...top3].sort().join("-"); break;
        case "sanrentan": hit = parts[0] === top3[0] && parts[1] === top3[1] && parts[2] === top3[2]; break;
      }

      const payout = hit ? trade.amount * trade.odds : 0;
      update.run(hit ? "hit" : "miss", payout, trade.id);
      settled++;
    }

    return NextResponse.json({ settled, raceId });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "決済失敗" },
      { status: 500 }
    );
  }
}
