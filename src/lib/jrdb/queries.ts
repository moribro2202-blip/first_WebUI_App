import { getDb } from "./db";

// --- レース検索 ---

export type JrdbRace = {
  race_id: string;
  race_date: string;
  venue_code: string;
  venue_name: string;
  race_number: number;
  race_name: string | null;
  distance: number;
  surface: string;
  track_condition: string | null;
  course_direction: string | null;
  head_count: number | null;
  start_time: string | null;
  grade: string | null;
};

export function getRacesByDate(date: string): JrdbRace[] {
  const db = getDb();
  return db
    .prepare("SELECT * FROM races WHERE race_date = ? ORDER BY venue_code, race_number")
    .all(date) as JrdbRace[];
}

export function getRaceById(raceId: string): JrdbRace | undefined {
  const db = getDb();
  return db.prepare("SELECT * FROM races WHERE race_id = ?").get(raceId) as
    | JrdbRace
    | undefined;
}

// --- 出走馬 ---

export type JrdbEntry = {
  race_id: string;
  horse_number: number;
  gate_number: number | null;
  horse_id: string | null;
  horse_name: string;
  jockey_name: string;
  trainer_name: string;
  carried_weight: number;
  horse_weight: number | null;
  horse_weight_diff: number | null;
  age: string | null;
  sex: string | null;
  odds_win: number | null;
  popularity: number | null;
};

export function getEntriesByRace(raceId: string): JrdbEntry[] {
  const db = getDb();
  return db
    .prepare("SELECT * FROM entries WHERE race_id = ? ORDER BY horse_number")
    .all(raceId) as JrdbEntry[];
}

// --- 過去成績 ---

export type JrdbResult = {
  race_id: string;
  horse_number: number;
  finish_position: number | null;
  finish_time: number | null;
  last_3f: number | null;
  corner_positions: string | null;
  jockey_name: string | null;
  carried_weight: number | null;
  horse_weight: number | null;
  horse_weight_diff: number | null;
  win_odds: number | null;
  popularity: number | null;
  // JOINで取得するレース情報
  race_date?: string;
  venue_name?: string;
  race_number?: number;
  distance?: number;
  surface?: string;
  track_condition?: string;
  race_name?: string;
};

export function getHorseResults(
  horseId: string,
  limit: number = 5
): JrdbResult[] {
  const db = getDb();
  return db
    .prepare(
      `SELECT r.*, ra.race_date, ra.venue_name, ra.race_number,
              ra.distance, ra.surface, ra.track_condition, ra.race_name
       FROM results r
       JOIN races ra ON r.race_id = ra.race_id
       WHERE r.horse_id = ?
       ORDER BY ra.race_date DESC
       LIMIT ?`
    )
    .all(horseId, limit) as JrdbResult[];
}

// --- 血統 ---

export type JrdbHorse = {
  horse_id: string;
  horse_name: string;
  birth_year: number | null;
  sex: string | null;
  sire: string | null;
  dam: string | null;
  dam_sire: string | null;
};

export function getHorse(horseId: string): JrdbHorse | undefined {
  const db = getDb();
  return db.prepare("SELECT * FROM horses WHERE horse_id = ?").get(horseId) as
    | JrdbHorse
    | undefined;
}

// --- 騎手成績 ---

export type JockeyStats = {
  jockey_name: string;
  total_rides: number;
  wins: number;
  win_rate: number;
  place_count: number;
  place_rate: number;
};

export function getJockeyStats(jockeyName: string): JockeyStats | undefined {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT
        jockey_name,
        COUNT(*) as total_rides,
        SUM(CASE WHEN finish_position = 1 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN finish_position <= 3 THEN 1 ELSE 0 END) as place_count
       FROM results
       WHERE jockey_name = ? AND finish_position IS NOT NULL
       GROUP BY jockey_name`
    )
    .get(jockeyName) as
    | { jockey_name: string; total_rides: number; wins: number; place_count: number }
    | undefined;

  if (!row) return undefined;

  return {
    jockey_name: row.jockey_name,
    total_rides: row.total_rides,
    wins: row.wins,
    win_rate: row.total_rides > 0 ? (row.wins / row.total_rides) * 100 : 0,
    place_count: row.place_count,
    place_rate:
      row.total_rides > 0 ? (row.place_count / row.total_rides) * 100 : 0,
  };
}

// --- 調教師成績 ---

export type TrainerStats = {
  trainer_name: string;
  total_entries: number;
  wins: number;
  win_rate: number;
  place_count: number;
  place_rate: number;
};

export function getTrainerStats(
  trainerName: string
): TrainerStats | undefined {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT
        e.trainer_name,
        COUNT(*) as total_entries,
        SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as place_count
       FROM entries e
       JOIN results r ON e.race_id = r.race_id AND e.horse_number = r.horse_number
       WHERE e.trainer_name = ? AND r.finish_position IS NOT NULL
       GROUP BY e.trainer_name`
    )
    .get(trainerName) as
    | { trainer_name: string; total_entries: number; wins: number; place_count: number }
    | undefined;

  if (!row) return undefined;

  return {
    trainer_name: row.trainer_name,
    total_entries: row.total_entries,
    wins: row.wins,
    win_rate:
      row.total_entries > 0 ? (row.wins / row.total_entries) * 100 : 0,
    place_count: row.place_count,
    place_rate:
      row.total_entries > 0
        ? (row.place_count / row.total_entries) * 100
        : 0,
  };
}

// --- 枠番傾向 ---

export type GateStats = {
  gate_number: number;
  total_entries: number;
  wins: number;
  win_rate: number;
  place_count: number;
  place_rate: number;
};

/**
 * 指定コース（競馬場+馬場+距離）での枠番別成績を取得
 * resultsテーブルの全データから、馬番→枠番推定で集計
 * JRA枠番: 8頭以下=馬番=枠番、9頭以上は上位馬番を2頭ずつ8枠に振る
 */
export function getGateStatsByCourse(
  venueCode: string,
  surface: string,
  distance: number
): GateStats[] {
  const db = getDb();

  // まず該当コースの全レースの頭数を取得してレースごとに枠番を推定
  const rows = db
    .prepare(
      `WITH race_counts AS (
        SELECT r.race_id, COUNT(*) as head_count
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE ra.venue_code = ? AND ra.surface = ? AND ra.distance = ?
          AND r.finish_position IS NOT NULL
        GROUP BY r.race_id
      )
      SELECT
        r.race_id, r.horse_number, r.finish_position, rc.head_count
      FROM results r
      JOIN races ra ON r.race_id = ra.race_id
      JOIN race_counts rc ON r.race_id = rc.race_id
      WHERE ra.venue_code = ? AND ra.surface = ? AND ra.distance = ?
        AND r.finish_position IS NOT NULL`
    )
    .all(venueCode, surface, distance, venueCode, surface, distance) as {
    race_id: string;
    horse_number: number;
    finish_position: number;
    head_count: number;
  }[];

  // 馬番→枠番変換して集計
  const gateMap = new Map<number, { total: number; wins: number; place: number }>();

  for (const r of rows) {
    const gate = horseNumberToGate(r.horse_number, r.head_count);
    if (gate < 1 || gate > 8) continue;

    const entry = gateMap.get(gate) ?? { total: 0, wins: 0, place: 0 };
    entry.total++;
    if (r.finish_position === 1) entry.wins++;
    if (r.finish_position <= 3) entry.place++;
    gateMap.set(gate, entry);
  }

  return Array.from(gateMap.entries())
    .sort(([a], [b]) => a - b)
    .map(([gate, stats]) => ({
      gate_number: gate,
      total_entries: stats.total,
      wins: stats.wins,
      win_rate: stats.total > 0 ? (stats.wins / stats.total) * 100 : 0,
      place_count: stats.place,
      place_rate: stats.total > 0 ? (stats.place / stats.total) * 100 : 0,
    }));
}

/**
 * JRAの枠番ルールに基づき馬番から枠番を推定
 * - 8頭以下: 馬番=枠番
 * - 9頭以上: 8枠側から順に2頭ずつ割当（17頭以上は3頭枠も発生）
 * 例: 11頭 → 1-5枠は1頭ずつ、6-8枠は2頭ずつ
 *     18頭 → 1-6枠は2頭ずつ、7-8枠は3頭ずつ
 */
function horseNumberToGate(horseNumber: number, headCount: number): number {
  if (headCount <= 8) return horseNumber;

  // 各枠の馬数を計算
  const gates = [1, 1, 1, 1, 1, 1, 1, 1];
  let remaining = headCount - 8;

  // 8枠側から順に1頭ずつ追加
  for (let g = 7; g >= 0 && remaining > 0; g--) {
    gates[g]++;
    remaining--;
  }
  // 17頭以上の場合、さらに追加
  for (let g = 7; g >= 0 && remaining > 0; g--) {
    gates[g]++;
    remaining--;
  }

  // 馬番→枠番を算出
  let cumulative = 0;
  for (let g = 0; g < 8; g++) {
    cumulative += gates[g];
    if (horseNumber <= cumulative) return g + 1;
  }
  return 8;
}

// --- 性別傾向 ---

export type SexStats = {
  sex: string;
  total_entries: number;
  wins: number;
  win_rate: number;
  place_count: number;
  place_rate: number;
};

/**
 * 指定コース（競馬場+馬場+距離）での性別別成績を取得
 * horsesテーブルのsexを使用して集計
 */
export function getSexStatsByCourse(
  venueCode: string,
  surface: string,
  distance: number
): SexStats[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT
        h.sex,
        COUNT(*) as total_entries,
        SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as place_count
       FROM results r
       JOIN horses h ON r.horse_id = h.horse_id
       JOIN races ra ON r.race_id = ra.race_id
       WHERE ra.venue_code = ?
         AND ra.surface = ?
         AND ra.distance = ?
         AND h.sex IS NOT NULL AND h.sex != ''
         AND r.finish_position IS NOT NULL
       GROUP BY h.sex
       ORDER BY h.sex`
    )
    .all(venueCode, surface, distance) as {
    sex: string;
    total_entries: number;
    wins: number;
    place_count: number;
  }[];

  return rows.map((row) => ({
    sex: row.sex,
    total_entries: row.total_entries,
    wins: row.wins,
    win_rate: row.total_entries > 0 ? (row.wins / row.total_entries) * 100 : 0,
    place_count: row.place_count,
    place_rate:
      row.total_entries > 0 ? (row.place_count / row.total_entries) * 100 : 0,
  }));
}

/**
 * 全レースでの性別別成績を取得（horsesテーブルのsex使用）
 */
export function getSexStatsAll(): SexStats[] {
  const db = getDb();
  const rows = db
    .prepare(
      `SELECT
        h.sex,
        COUNT(*) as total_entries,
        SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
        SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as place_count
       FROM results r
       JOIN horses h ON r.horse_id = h.horse_id
       WHERE h.sex IS NOT NULL AND h.sex != ''
         AND r.finish_position IS NOT NULL
       GROUP BY h.sex
       ORDER BY h.sex`
    )
    .all() as {
    sex: string;
    total_entries: number;
    wins: number;
    place_count: number;
  }[];

  return rows.map((row) => ({
    sex: row.sex,
    total_entries: row.total_entries,
    wins: row.wins,
    win_rate: row.total_entries > 0 ? (row.wins / row.total_entries) * 100 : 0,
    place_count: row.place_count,
    place_rate:
      row.total_entries > 0 ? (row.place_count / row.total_entries) * 100 : 0,
  }));
}

/**
 * 全レースでの枠番別成績を取得（フォールバック用）
 */
export function getGateStatsAll(): GateStats[] {
  const db = getDb();
  const rows = db
    .prepare(
      `WITH race_counts AS (
        SELECT race_id, COUNT(*) as head_count
        FROM results
        WHERE finish_position IS NOT NULL
        GROUP BY race_id
      )
      SELECT r.horse_number, r.finish_position, rc.head_count
      FROM results r
      JOIN race_counts rc ON r.race_id = rc.race_id
      WHERE r.finish_position IS NOT NULL`
    )
    .all() as {
    horse_number: number;
    finish_position: number;
    head_count: number;
  }[];

  const gateMap = new Map<number, { total: number; wins: number; place: number }>();

  for (const r of rows) {
    const gate = horseNumberToGate(r.horse_number, r.head_count);
    if (gate < 1 || gate > 8) continue;

    const entry = gateMap.get(gate) ?? { total: 0, wins: 0, place: 0 };
    entry.total++;
    if (r.finish_position === 1) entry.wins++;
    if (r.finish_position <= 3) entry.place++;
    gateMap.set(gate, entry);
  }

  return Array.from(gateMap.entries())
    .sort(([a], [b]) => a - b)
    .map(([gate, stats]) => ({
      gate_number: gate,
      total_entries: stats.total,
      wins: stats.wins,
      win_rate: stats.total > 0 ? (stats.wins / stats.total) * 100 : 0,
      place_count: stats.place,
      place_rate: stats.total > 0 ? (stats.place / stats.total) * 100 : 0,
    }));
}

// --- 長期休養リスク ---

export type LayoffRisk = {
  horse_name: string;
  last_race_date: string;
  days_since_last_race: number;
  risk: "high" | "moderate" | "none";
};

const LAYOFF_HIGH_DAYS = 180; // 6ヶ月以上
const LAYOFF_MODERATE_DAYS = 90; // 3ヶ月以上

/**
 * 馬の長期休養リスクを判定する
 * @param referenceDate 基準日（レース開催日）YYYY-MM-DD
 */
export function checkLayoffRisk(
  horseId: string,
  referenceDate: string
): LayoffRisk | null {
  const db = getDb();
  const row = db
    .prepare(
      `SELECT r.horse_id, ra.race_date
       FROM results r
       JOIN races ra ON r.race_id = ra.race_id
       WHERE r.horse_id = ? AND ra.race_date < ?
       ORDER BY ra.race_date DESC
       LIMIT 1`
    )
    .get(horseId, referenceDate) as
    | { horse_id: string; race_date: string }
    | undefined;

  if (!row) return null;

  const last = new Date(row.race_date);
  const ref = new Date(referenceDate);
  const diffMs = ref.getTime() - last.getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  let risk: LayoffRisk["risk"] = "none";
  if (days >= LAYOFF_HIGH_DAYS) risk = "high";
  else if (days >= LAYOFF_MODERATE_DAYS) risk = "moderate";

  const horse = getHorse(horseId);

  return {
    horse_name: horse?.horse_name ?? "",
    last_race_date: row.race_date,
    days_since_last_race: days,
    risk,
  };
}

// --- 馬体重変動チェック ---

export type WeightAlert = {
  horse_name: string;
  current_weight: number;
  previous_weight: number;
  diff: number;
  alert: "increase" | "decrease" | "normal";
};

const WEIGHT_ALERT_THRESHOLD = 10; // kg

export function checkWeightAlert(
  horseId: string,
  currentWeight: number
): WeightAlert | null {
  const db = getDb();
  const prev = db
    .prepare(
      `SELECT r.horse_weight, r.horse_id
       FROM results r
       JOIN races ra ON r.race_id = ra.race_id
       WHERE r.horse_id = ? AND r.horse_weight IS NOT NULL
       ORDER BY ra.race_date DESC
       LIMIT 1`
    )
    .get(horseId) as { horse_weight: number } | undefined;

  if (!prev || !currentWeight) return null;

  const horse = getHorse(horseId);
  const diff = currentWeight - prev.horse_weight;
  let alert: WeightAlert["alert"] = "normal";

  if (diff >= WEIGHT_ALERT_THRESHOLD) alert = "increase";
  else if (diff <= -WEIGHT_ALERT_THRESHOLD) alert = "decrease";

  return {
    horse_name: horse?.horse_name ?? "",
    current_weight: currentWeight,
    previous_weight: prev.horse_weight,
    diff,
    alert,
  };
}

// --- ラップタイム ---

export type LapTime = {
  section_number: number;
  section_time: number;
};

export function getLapTimes(raceId: string): LapTime[] {
  const db = getDb();
  return db
    .prepare(
      "SELECT section_number, section_time FROM lap_times WHERE race_id = ? ORDER BY section_number"
    )
    .all(raceId) as LapTime[];
}

// --- インポートログ ---

export type ImportLogEntry = {
  id: number;
  file_name: string;
  file_type: string;
  record_count: number | null;
  status: string;
  error_message: string | null;
  imported_at: string;
};

export function getImportLog(limit: number = 20): ImportLogEntry[] {
  const db = getDb();
  return db
    .prepare("SELECT * FROM import_log ORDER BY imported_at DESC LIMIT ?")
    .all(limit) as ImportLogEntry[];
}

// --- DB統計 ---

export type DbStats = {
  races: number;
  entries: number;
  results: number;
  horses: number;
};

export function getDbStats(): DbStats {
  const db = getDb();
  const count = (table: string) =>
    (db.prepare(`SELECT COUNT(*) as c FROM ${table}`).get() as { c: number }).c;

  return {
    races: count("races"),
    entries: count("entries"),
    results: count("results"),
    horses: count("horses"),
  };
}
