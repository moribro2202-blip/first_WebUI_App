import { NextResponse } from "next/server";
import { getDb } from "@/lib/jrdb/db";

/** データ状況・運用チェックリストAPI */
export async function GET() {
  const db = getDb();

  const today = new Date().toISOString().slice(0, 10);
  const tomorrow = new Date(Date.now() + 86400000).toISOString().slice(0, 10);

  function checkDate(date: string) {
    const races = (db.prepare("SELECT COUNT(*) as c FROM races WHERE race_date=?").get(date) as {c:number}).c;
    const entries = (db.prepare("SELECT COUNT(*) as c FROM entries WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?)").get(date) as {c:number}).c;
    const idm = (db.prepare("SELECT COUNT(*) as c FROM entries WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?) AND idm IS NOT NULL AND idm > 0").get(date) as {c:number}).c;
    const winOdds = (db.prepare("SELECT COUNT(*) as c FROM odds WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?) AND bet_type='win'").get(date) as {c:number}).c;
    const trioOdds = (db.prepare("SELECT COUNT(*) as c FROM odds WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?) AND bet_type='sanrenpuku'").get(date) as {c:number}).c;
    const results = (db.prepare("SELECT COUNT(*) as c FROM results WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?) AND finish_position IS NOT NULL").get(date) as {c:number}).c;
    const pending = (db.prepare("SELECT COUNT(*) as c FROM paper_trades WHERE race_date=? AND result='pending'").get(date) as {c:number}).c;
    const settled = (db.prepare("SELECT COUNT(*) as c FROM paper_trades WHERE race_date=? AND result IN ('hit','miss')").get(date) as {c:number}).c;

    return {
      date, races, entries, idm, winOdds, trioOdds, results, pending, settled,
      canPredict: races > 0 && idm > 0 && winOdds > 0,
      canSettle: pending > 0 && results > 0,
      needsData: races > 0 && (idm === 0 || winOdds === 0),
    };
  }

  const latestRace = (db.prepare("SELECT MAX(race_date) as d FROM races").get() as {d:string})?.d;
  const latestResult = (db.prepare("SELECT MAX(r.race_date) as d FROM races r JOIN results res ON r.race_id=res.race_id WHERE res.finish_position IS NOT NULL").get() as {d:string})?.d;
  const pendingTotal = (db.prepare("SELECT COUNT(*) as c FROM paper_trades WHERE result='pending'").get() as {c:number}).c;

  // Checklist
  const todayData = checkDate(today);
  const tomorrowData = checkDate(tomorrow);

  const checklist = [];
  if (todayData.canPredict && todayData.settled === 0 && todayData.pending === 0) {
    checklist.push({ action: "predict", label: `${today}の予測を記録`, priority: "high" });
  }
  if (todayData.canSettle) {
    checklist.push({ action: "settle", label: `${today}の${todayData.pending}件を決済`, priority: "high" });
  }
  if (pendingTotal > 0) {
    checklist.push({ action: "settle_all", label: `未決済${pendingTotal}件あり（結果データをインポート）`, priority: "medium" });
  }
  if (tomorrowData.needsData) {
    checklist.push({ action: "import", label: `${tomorrow}のKYI/OZが必要`, priority: "high" });
  }
  if (!tomorrowData.races) {
    checklist.push({ action: "import", label: `${tomorrow}のBACが必要`, priority: "medium" });
  }

  return NextResponse.json({
    today: todayData,
    tomorrow: tomorrowData,
    latestRace,
    latestResult,
    pendingTotal,
    checklist,
  });
}
