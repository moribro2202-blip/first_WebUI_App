import { NextRequest, NextResponse } from "next/server";
import {
  getRaceById,
  getEntriesByRace,
  getHorseResults,
  getHorse,
  getJockeyStats,
  getTrainerStats,
  checkWeightAlert,
  getLapTimes,
  getGateStatsByCourse,
  getSexStatsByCourse,
  getGateStatsAll,
  getSexStatsAll,
  checkLayoffRisk,
} from "@/lib/jrdb/queries";

type Props = {
  params: Promise<{ raceId: string }>;
};

export async function GET(_request: NextRequest, { params }: Props) {
  const { raceId } = await params;

  try {
    const race = getRaceById(raceId);
    if (!race) {
      return NextResponse.json({ error: "レースが見つかりません" }, { status: 404 });
    }

    const entries = getEntriesByRace(raceId);
    const lapTimes = getLapTimes(raceId);

    // 枠番傾向：コース別 → 空ならば全体
    let gateStats = getGateStatsByCourse(
      race.venue_code,
      race.surface,
      race.distance
    );
    if (gateStats.length === 0) {
      gateStats = getGateStatsAll();
    }

    // 性別傾向：コース別 → 空ならば全体
    let sexStats = getSexStatsByCourse(
      race.venue_code,
      race.surface,
      race.distance
    );
    if (sexStats.length === 0) {
      sexStats = getSexStatsAll();
    }

    // OZテーブルから前日オッズを取得してentriesにマージ
    try {
      const { getDb } = await import("@/lib/jrdb/db");
      const db = getDb();
      const ozWin = db
        .prepare(
          "SELECT combination, odds FROM odds WHERE race_id = ? AND bet_type = 'win'"
        )
        .all(raceId) as { combination: string; odds: number }[];

      for (const entry of entries) {
        const oz = ozWin.find(
          (r) => parseInt(r.combination) === entry.horse_number
        );
        if (oz && (!entry.odds_win || entry.odds_win === 0)) {
          entry.odds_win = oz.odds;
        }
      }

      // 人気順をオッズから算出（低オッズ順）
      const sorted = [...entries]
        .filter((e) => e.odds_win && e.odds_win > 0)
        .sort((a, b) => (a.odds_win ?? 999) - (b.odds_win ?? 999));
      for (let i = 0; i < sorted.length; i++) {
        const entry = entries.find(
          (e) => e.horse_number === sorted[i].horse_number
        );
        if (entry && (!entry.popularity || entry.popularity === 0)) {
          entry.popularity = i + 1;
        }
      }
    } catch {
      // OZデータなしの場合はスキップ
    }

    // 各馬の追加情報を取得
    const enrichedEntries = entries.map((entry) => {
      const pastResults = entry.horse_id
        ? getHorseResults(entry.horse_id, 5)
        : [];
      const pedigree = entry.horse_id ? getHorse(entry.horse_id) : null;
      const jockeyStats = getJockeyStats(entry.jockey_name);
      const trainerStats = getTrainerStats(entry.trainer_name);
      const weightAlert =
        entry.horse_id && entry.horse_weight
          ? checkWeightAlert(entry.horse_id, entry.horse_weight)
          : null;
      const layoffRisk =
        entry.horse_id && race.race_date
          ? checkLayoffRisk(entry.horse_id, race.race_date)
          : null;

      return {
        ...entry,
        pastResults,
        pedigree,
        jockeyStats,
        trainerStats,
        weightAlert,
        layoffRisk,
      };
    });

    return NextResponse.json({
      race,
      entries: enrichedEntries,
      lapTimes,
      gateStats,
      sexStats,
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取得に失敗しました" },
      { status: 500 }
    );
  }
}
