import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/jrdb/db";

/**
 * モデル監視API
 * リアルタイム投票の成績を集計（ペーパー/実投票/全体）
 * 固定額投資前提で回収率・累積損益を監視
 */
export async function GET(request: NextRequest) {
  try {
    const db = getDb();
    const filter = request.nextUrl.searchParams.get("filter") || "all";
    // filter: "paper" | "live" | "all"

    const whereClause = filter === "paper"
      ? "AND is_live = 0"
      : filter === "live"
        ? "AND is_live = 1"
        : "";

    // 日別成績
    const daily = db.prepare(`
      SELECT race_date,
        COUNT(*) as bets,
        SUM(amount) as invested,
        SUM(CASE WHEN result='hit' THEN payout ELSE 0 END) as payout,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as misses,
        SUM(CASE WHEN result IS NULL THEN 1 ELSE 0 END) as pending,
        AVG(ev) as avg_ev,
        AVG(model_prob) as avg_prob,
        AVG(odds_at_bet) as avg_odds
      FROM realtime_bets
      WHERE 1=1 ${whereClause}
      GROUP BY race_date ORDER BY race_date
    `).all() as Array<{
      race_date: string; bets: number; invested: number; payout: number;
      hits: number; misses: number; pending: number;
      avg_ev: number; avg_prob: number; avg_odds: number;
    }>;

    let cumPnl = 0;
    const dailyWithCum = daily.map(d => {
      const settled = d.hits + d.misses;
      const settledInvest = settled > 0 ? (d.invested / d.bets) * settled : 0;
      const pnl = (d.payout || 0) - settledInvest;
      cumPnl += pnl;
      const rec = settledInvest > 0 ? ((d.payout || 0) / settledInvest) * 100 : null;
      return { ...d, pnl, cumPnl, rec };
    });

    // 全体集計
    const totals = db.prepare(`
      SELECT
        COUNT(*) as total_bets,
        SUM(amount) as total_invested,
        SUM(CASE WHEN result='hit' THEN payout ELSE 0 END) as total_payout,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        SUM(CASE WHEN result='miss' THEN 1 ELSE 0 END) as misses,
        SUM(CASE WHEN result IS NULL THEN 1 ELSE 0 END) as pending,
        AVG(ev) as avg_ev,
        AVG(model_prob) as avg_prob,
        AVG(odds_at_bet) as avg_odds
      FROM realtime_bets
      WHERE 1=1 ${whereClause}
    `).get() as {
      total_bets: number; total_invested: number; total_payout: number;
      hits: number; misses: number; pending: number;
      avg_ev: number; avg_prob: number; avg_odds: number;
    };

    const settled = totals.hits + totals.misses;
    const settledInvest = settled > 0 && totals.total_bets > 0
      ? (totals.total_invested / totals.total_bets) * settled : 0;
    const totalRec = settledInvest > 0 ? ((totals.total_payout || 0) / settledInvest) * 100 : null;

    // EV帯別成績
    const evBands = db.prepare(`
      SELECT
        CASE
          WHEN ev < 1.0 THEN '0-1.0'
          WHEN ev < 1.1 THEN '1.0-1.1'
          WHEN ev < 1.2 THEN '1.1-1.2'
          WHEN ev < 1.5 THEN '1.2-1.5'
          ELSE '1.5+'
        END as ev_band,
        COUNT(*) as n,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        SUM(amount) as invested,
        SUM(CASE WHEN result='hit' THEN payout ELSE 0 END) as payout,
        AVG(model_prob) as avg_prob,
        AVG(odds_at_bet) as avg_odds
      FROM realtime_bets
      WHERE result IN ('hit','miss') ${whereClause}
      GROUP BY ev_band ORDER BY ev_band
    `).all() as Array<{
      ev_band: string; n: number; hits: number;
      invested: number; payout: number; avg_prob: number; avg_odds: number;
    }>;

    // オッズ帯別成績
    const oddsBands = db.prepare(`
      SELECT
        CASE
          WHEN odds_at_bet < 3 THEN '1-3x'
          WHEN odds_at_bet < 5 THEN '3-5x'
          WHEN odds_at_bet < 10 THEN '5-10x'
          WHEN odds_at_bet < 20 THEN '10-20x'
          WHEN odds_at_bet < 30 THEN '20-30x'
          WHEN odds_at_bet < 40 THEN '30-40x'
          ELSE '40x+'
        END as odds_band,
        COUNT(*) as n,
        SUM(CASE WHEN result='hit' THEN 1 ELSE 0 END) as hits,
        SUM(amount) as invested,
        SUM(CASE WHEN result='hit' THEN payout ELSE 0 END) as payout,
        AVG(model_prob) as avg_prob
      FROM realtime_bets
      WHERE result IN ('hit','miss') ${whereClause}
      GROUP BY odds_band ORDER BY odds_band
    `).all() as Array<{
      odds_band: string; n: number; hits: number;
      invested: number; payout: number; avg_prob: number;
    }>;

    // 連敗分析
    const allResults = db.prepare(`
      SELECT result FROM realtime_bets
      WHERE result IN ('hit','miss') ${whereClause}
      ORDER BY created_at
    `).all() as Array<{ result: string }>;

    let maxStreak = 0; let currentStreak = 0;
    const streakList: number[] = [];
    for (const t of allResults) {
      if (t.result === "miss") {
        currentStreak++;
        if (currentStreak > maxStreak) maxStreak = currentStreak;
      } else {
        if (currentStreak > 0) streakList.push(currentStreak);
        currentStreak = 0;
      }
    }
    if (currentStreak > 0) streakList.push(currentStreak);

    // キャリブレーション（予測確率 vs 実勝率）
    const calData = db.prepare(`
      SELECT model_prob, CASE WHEN result='hit' THEN 1.0 ELSE 0.0 END as is_hit
      FROM realtime_bets
      WHERE result IN ('hit','miss') ${whereClause}
      ORDER BY model_prob
    `).all() as Array<{ model_prob: number; is_hit: number }>;

    const calBuckets: Array<{ range: string; n: number; predicted: number; actual: number; ratio: number }> = [];
    if (calData.length >= 20) {
      const bucketSize = Math.floor(calData.length / 5);
      for (let i = 0; i < 5; i++) {
        const start = i * bucketSize;
        const end = i === 4 ? calData.length : start + bucketSize;
        const bucket = calData.slice(start, end);
        const avgP = bucket.reduce((s, b) => s + b.model_prob, 0) / bucket.length;
        const avgH = bucket.reduce((s, b) => s + b.is_hit, 0) / bucket.length;
        calBuckets.push({
          range: `${bucket[0].model_prob.toFixed(3)}-${bucket[bucket.length - 1].model_prob.toFixed(3)}`,
          n: bucket.length,
          predicted: avgP,
          actual: avgH,
          ratio: avgP > 0 ? avgH / avgP : 0,
        });
      }
    }

    return NextResponse.json({
      filter,
      daily: dailyWithCum,
      totals: {
        ...totals,
        settled,
        settledInvest,
        rec: totalRec,
      },
      evBands,
      oddsBands,
      streaks: {
        max: maxStreak,
        current: currentStreak,
        avg: streakList.length > 0 ? streakList.reduce((a, b) => a + b, 0) / streakList.length : 0,
        over10: streakList.filter(s => s >= 10).length,
        over20: streakList.filter(s => s >= 20).length,
      },
      calibration: calBuckets,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取得失敗" },
      { status: 500 }
    );
  }
}
