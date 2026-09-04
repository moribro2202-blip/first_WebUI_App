import { NextResponse } from "next/server";
import { getDb } from "@/lib/jrdb/db";

/**
 * M7モデル監視API
 * 月別成績、キャリブレーション、連敗分析を返す
 */
export async function GET() {
  try {
    const db = getDb();

    // Monthly stats from paper_trades
    const monthly = db.prepare(`
      SELECT substr(race_date, 1, 7) as month,
        COUNT(*) as races,
        SUM(amount) as invested,
        SUM(CASE WHEN result='hit' THEN payout ELSE 0 END) as payout,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as misses,
        SUM(CASE WHEN result='pending' THEN 1 ELSE 0 END) as pending,
        AVG(CASE WHEN result='hit' THEN payout / amount ELSE NULL END) as avg_hit_odds
      FROM paper_trades
      WHERE ai_score_json LIKE '%M7%'
      GROUP BY month ORDER BY month
    `).all() as Array<{
      month: string; races: number; invested: number; payout: number;
      hits: number; misses: number; pending: number; avg_hit_odds: number | null;
    }>;

    // Cumulative PnL
    let cumPnl = 0;
    const cumulative = monthly.map(m => {
      const settled = m.hits + m.misses;
      const monthPnl = (m.payout ?? 0) - (settled > 0 ? m.invested * settled / m.races : 0);
      cumPnl += monthPnl;
      const rr = m.invested > 0 && settled > 0
        ? (m.payout / (m.invested * settled / m.races)) * 100
        : null;
      return {
        ...m,
        rr,
        pnl: monthPnl,
        cumPnl,
        hitRate: settled > 0 ? (m.hits / settled) * 100 : null,
      };
    });

    // Calibration: predicted prob vs actual hit rate by PredBlend bucket
    // Extract predBlend from ai_score_json
    const allTrades = db.prepare(`
      SELECT ai_score_json, result FROM paper_trades
      WHERE ai_score_json LIKE '%M7%' AND result IN ('hit', 'miss')
    `).all() as Array<{ ai_score_json: string; result: string }>;

    const buckets: Record<string, { count: number; hits: number; sumProb: number }> = {};
    const bucketEdges = [0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 1.0];

    for (const trade of allTrades) {
      try {
        const score = JSON.parse(trade.ai_score_json);
        const prob = score.trioProb ?? 0;
        for (let i = 0; i < bucketEdges.length - 1; i++) {
          if (prob >= bucketEdges[i] && prob < bucketEdges[i + 1]) {
            const key = `${bucketEdges[i].toFixed(2)}-${bucketEdges[i + 1].toFixed(2)}`;
            if (!buckets[key]) buckets[key] = { count: 0, hits: 0, sumProb: 0 };
            buckets[key].count++;
            buckets[key].sumProb += prob;
            if (trade.result === "hit") buckets[key].hits++;
            break;
          }
        }
      } catch { /* skip */ }
    }

    const calibration = Object.entries(buckets)
      .map(([range, data]) => ({
        range,
        count: data.count,
        predicted: data.sumProb / data.count,
        actual: data.hits / data.count,
        ratio: (data.hits / data.count) / (data.sumProb / data.count),
      }))
      .sort((a, b) => a.predicted - b.predicted);

    // Streak analysis
    let maxStreak = 0;
    let currentStreak = 0;
    const streaks: number[] = [];
    const recentTrades = db.prepare(`
      SELECT result FROM paper_trades
      WHERE ai_score_json LIKE '%M7%' AND result IN ('hit', 'miss')
      ORDER BY race_date, race_id
    `).all() as Array<{ result: string }>;

    for (const t of recentTrades) {
      if (t.result === "miss") {
        currentStreak++;
        if (currentStreak > maxStreak) maxStreak = currentStreak;
      } else {
        if (currentStreak > 0) streaks.push(currentStreak);
        currentStreak = 0;
      }
    }
    if (currentStreak > 0) streaks.push(currentStreak);

    // Rolling 100-race hit rate (for degradation detection)
    const rolling: Array<{ idx: number; hitRate: number }> = [];
    const windowSize = 100;
    for (let i = windowSize; i <= recentTrades.length; i++) {
      const window = recentTrades.slice(i - windowSize, i);
      const hr = window.filter(t => t.result === "hit").length / windowSize * 100;
      rolling.push({ idx: i, hitRate: hr });
    }

    // Recent trend (last 200 vs all)
    const totalSettled = recentTrades.length;
    const totalHits = recentTrades.filter(t => t.result === "hit").length;
    const overallHR = totalSettled > 0 ? totalHits / totalSettled * 100 : 0;
    const recent200 = recentTrades.slice(-200);
    const recent200HR = recent200.length > 0
      ? recent200.filter(t => t.result === "hit").length / recent200.length * 100
      : 0;

    return NextResponse.json({
      monthly: cumulative,
      calibration,
      streaks: {
        max: maxStreak,
        current: currentStreak,
        over10: streaks.filter(s => s >= 10).length,
        over20: streaks.filter(s => s >= 20).length,
        avg: streaks.length > 0 ? streaks.reduce((a, b) => a + b, 0) / streaks.length : 0,
      },
      rolling,
      trend: {
        totalRaces: totalSettled,
        totalHits,
        overallHR,
        recent200HR,
        delta: recent200HR - overallHR,
        status: recent200HR >= overallHR - 2 ? "stable" : "degrading",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取得失敗" },
      { status: 500 }
    );
  }
}
