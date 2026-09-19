import { NextRequest, NextResponse } from "next/server";
import { getDb } from "@/lib/jrdb/db";

/**
 * リアルタイム投票API
 * GET: 設定・状況・結果一覧取得
 * POST: 設定変更
 */

export async function GET() {
  const db = getDb();
  // JST (UTC+9)
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const today = jst.toISOString().slice(0, 10);

  // 設定
  const configRows = db.prepare("SELECT key, value FROM realtime_config").all() as Array<{ key: string; value: string }>;
  const config: Record<string, string> = {};
  for (const row of configRows) config[row.key] = row.value;

  // 本日のオッズスナップショット数
  const oddsCount = (db.prepare(
    "SELECT COUNT(*) as c FROM realtime_odds WHERE race_date=?"
  ).get(today) as { c: number }).c;

  // 本日の投票記録（no_betは除外）
  const bets = db.prepare(`
    SELECT id, race_id, venue_name, race_number, horse_number, amount,
           odds_at_bet, model_prob, ev, move, status, is_live, result,
           payout, confirmed_odds, winner_number, settled_at, created_at
    FROM realtime_bets WHERE race_date=? AND status != 'no_bet' ORDER BY created_at DESC
  `).all(today) as Array<{
    id: number; race_id: string; venue_name: string; race_number: number;
    horse_number: number; amount: number; odds_at_bet: number;
    model_prob: number; ev: number; move: number; status: string;
    is_live: number; result: string | null; payout: number | null;
    confirmed_odds: number | null; winner_number: number | null;
    settled_at: string | null; created_at: string;
  }>;

  // 本日のレース結果
  const results = db.prepare(`
    SELECT race_id, venue_name, race_number, winner_number, winner_odds, checked_at
    FROM realtime_results WHERE race_date=? ORDER BY race_number
  `).all(today) as Array<{
    race_id: string; venue_name: string; race_number: number;
    winner_number: number; winner_odds: number; checked_at: string;
  }>;

  // 本日のオッズスナップショット（レースごとのサマリ）
  const snapshots = db.prepare(`
    SELECT race_id, venue_name, race_number, snapshot_label, COUNT(*) as horses,
           MIN(odds) as min_odds, snapshot_time
    FROM realtime_odds WHERE race_date=?
    GROUP BY race_id, snapshot_label
    ORDER BY snapshot_time
  `).all(today) as Array<{
    race_id: string; venue_name: string; race_number: number;
    snapshot_label: string; horses: number; min_odds: number; snapshot_time: string;
  }>;

  // 本日のオッズ詳細（全馬）
  const oddsDetail = db.prepare(`
    SELECT race_id, venue_name, race_number, snapshot_label, horse_number, odds, snapshot_time
    FROM realtime_odds WHERE race_date=?
    ORDER BY race_id, snapshot_label, horse_number
  `).all(today) as Array<{
    race_id: string; venue_name: string; race_number: number;
    snapshot_label: string; horse_number: number; odds: number; snapshot_time: string;
  }>;

  // 全レースの予測一覧
  const predictions = db.prepare(`
    SELECT race_id, venue_name, race_number, horse_number, odds, model_prob, ev, move, should_bet, created_at
    FROM realtime_predictions WHERE race_date=?
    ORDER BY race_number, ev DESC
  `).all(today) as Array<{
    race_id: string; venue_name: string; race_number: number;
    horse_number: number; odds: number; model_prob: number;
    ev: number; move: number; should_bet: number; created_at: string;
  }>;

  // 本日のレース一覧（締切時刻付き）
  const races = db.prepare(`
    SELECT race_id, venue_name, race_number, surface, distance, start_time, race_name, grade
    FROM races WHERE race_date=? ORDER BY start_time, venue_name, race_number
  `).all(today) as Array<{
    race_id: string; venue_name: string; race_number: number;
    surface: string; distance: number; start_time: string;
    race_name: string | null; grade: string | null;
  }>;

  // 締切時刻はstart_timeの1分前（即PATの実測値に基づく）
  const racesWithDeadline = races.map(r => {
    let deadline = r.start_time;
    if (r.start_time) {
      const [h, m] = r.start_time.split(":").map(Number);
      const totalMin = h * 60 + m - 1;
      deadline = `${String(Math.floor(totalMin / 60)).padStart(2, "0")}:${String(totalMin % 60).padStart(2, "0")}`;
    }
    // このレースのオッズ記録状況
    const snapshotCount = (db.prepare(
      "SELECT COUNT(DISTINCT snapshot_label) as c FROM realtime_odds WHERE race_id=?"
    ).get(r.race_id) as { c: number }).c;
    // 投票状況
    const betRows = db.prepare(
      "SELECT status, is_live, horse_number, ev, odds_at_bet, amount FROM realtime_bets WHERE race_id=? ORDER BY ev DESC"
    ).all(r.race_id) as Array<{ status: string; is_live: number; horse_number: number; ev: number; odds_at_bet: number; amount: number }>;
    // 投票ステータス判定
    let betStatus: string = "waiting"; // 未処理
    if (betRows.length > 0) {
      const statuses = betRows.map(b => b.status);
      if (statuses.includes("success")) betStatus = "live_bet";
      else if (statuses.includes("paper")) betStatus = "paper_bet";
      else if (statuses.includes("no_bet")) betStatus = "no_bet";
      else if (statuses.includes("failed")) betStatus = "failed";
      else betStatus = betRows[0].status;
    }
    // top EV
    const topBet = betRows.length > 0 ? betRows[0] : null;
    // 結果
    const result = db.prepare(
      "SELECT winner_number, winner_odds FROM realtime_results WHERE race_id=?"
    ).get(r.race_id) as { winner_number: number; winner_odds: number } | undefined;

    return {
      ...r,
      deadline,
      snapshotCount,
      betStatus,
      betCount: betRows.filter(b => b.status !== "no_bet").length,
      topEv: topBet?.ev ?? null,
      topHorse: topBet?.horse_number ?? null,
      topOdds: topBet?.odds_at_bet ?? null,
      winner: result?.winner_number ?? null,
      winnerOdds: result?.winner_odds ?? null,
    };
  });

  // 集計
  const activeBets = bets.filter(b => b.status !== "no_bet");
  const totalBets = activeBets.length;
  const totalInvested = activeBets.reduce((s, b) => s + (b.amount || 0), 0);
  const totalPayout = bets.reduce((s, b) => s + (b.payout || 0), 0);
  const hits = bets.filter(b => b.result === "hit").length;
  const misses = bets.filter(b => b.result === "miss").length;
  const pending = bets.filter(b => !b.result).length;

  return NextResponse.json({
    config,
    today,
    stats: { totalBets, totalInvested, totalPayout, hits, misses, pending, oddsCount },
    bets,
    results,
    snapshots,
    predictions,
    races: racesWithDeadline,
    oddsDetail,
  });
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const db = getDb();

    const allowedKeys = ["mode", "amount", "ev_threshold", "ev_threshold_trio", "odds_min", "odds_max"];
    let updated = 0;

    for (const key of allowedKeys) {
      if (key in body) {
        db.prepare(
          "INSERT OR REPLACE INTO realtime_config (key, value, updated_at) VALUES (?, ?, datetime('now','localtime'))"
        ).run(key, String(body[key]));
        updated++;
      }
    }

    // 現在の設定を返す
    const configRows = db.prepare("SELECT key, value FROM realtime_config").all() as Array<{ key: string; value: string }>;
    const config: Record<string, string> = {};
    for (const row of configRows) config[row.key] = row.value;

    return NextResponse.json({ updated, config });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "設定更新に失敗" },
      { status: 500 }
    );
  }
}
