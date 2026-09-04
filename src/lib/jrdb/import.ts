import fs from "fs";
import path from "path";
import { getDb, getJrdbDataDir } from "./db";
import { readFileLines, extractField, VENUE_CODES } from "./utils";

/**
 * 実データ検証済みのフィールド位置定義
 * BAC: 182バイト/行, KYI: 1022バイト/行, SED: 374バイト/行, UKC: 290バイト/行
 */

function buildRaceId(
  venueCode: string,
  year: string,
  kai: string,
  raceNumber: number
): string {
  return `${year}${venueCode}${kai}${String(raceNumber).padStart(2, "0")}`;
}

function parseSex(code: string): string {
  switch (code) {
    case "1": return "牡";
    case "2": return "牝";
    case "3": return "セ";
    default: return code;
  }
}

function parseSurface(code: string): string {
  switch (code) {
    case "1": return "芝";
    case "2": return "ダート";
    case "3": return "障害";
    default: return code;
  }
}

type ImportResult = {
  file: string;
  type: string;
  records: number;
  status: "success" | "error";
  error?: string;
};

export function importJrdbFiles(): ImportResult[] {
  const dataDir = getJrdbDataDir();
  const results: ImportResult[] = [];

  // UKCは先にインポート（馬マスタは依存なし）
  const importOrder = ["UKC", "BAC", "KYI", "SED", "OZ", "OW", "OU", "OT", "OV"];
  for (const subdir of importOrder) {
    const dir = path.join(dataDir, subdir);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
      continue;
    }

    const files = fs.readdirSync(dir).filter((f) => f.endsWith(".txt"));
    for (const file of files) {
      const filePath = path.join(dir, file);
      try {
        let count = 0;
        switch (subdir) {
          case "BAC":
            count = importBacFile(filePath);
            break;
          case "KYI":
            count = importKyiFile(filePath);
            break;
          case "SED":
            count = importSedFile(filePath);
            break;
          case "UKC":
            count = importUkcFile(filePath);
            break;
          case "OZ":
            count = importOzFile(filePath);
            break;
          case "OW":
            count = importOwFile(filePath);
            break;
          case "OU":
            count = importOuFile(filePath);
            break;
          case "OT":
            count = importOtFile(filePath);
            break;
          case "OV":
            count = importOvFile(filePath);
            break;
        }
        results.push({ file, type: subdir, records: count, status: "success" });
        logImport(file, subdir, count, "success");
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        results.push({ file, type: subdir, records: 0, status: "error", error: msg });
        logImport(file, subdir, 0, "error", msg);
      }
    }
  }

  return results;
}

function logImport(
  fileName: string,
  fileType: string,
  recordCount: number,
  status: string,
  errorMessage?: string
) {
  const db = getDb();
  db.prepare(
    `INSERT INTO import_log (file_name, file_type, record_count, status, error_message)
     VALUES (?, ?, ?, ?, ?)`
  ).run(fileName, fileType, recordCount, status, errorMessage ?? null);
}

/**
 * BAC: レース番組データ (182バイト/行)
 * 0-1: 場コード(2), 2-3: 年(2), 4-5: 回次(2), 6-7: R番号(2)
 * 8-15: 年月日(8,YYYYMMDD), 16-19: 発走時刻(4,HHMM)
 * 20-23: 距離(4), 24: 芝ダ障(1), 25: 右左(1)
 */
function parseTrackCondition(code: string): string | null {
  const map: Record<string, string> = {
    "11": "良", "12": "稍重", "13": "重", "14": "不良",
    "21": "良", "22": "稍重", "23": "重", "24": "不良",
  };
  return map[code] ?? null;
}

function parseWeather(code: string): string | null {
  const map: Record<string, string> = {
    "1": "晴", "2": "曇", "3": "雨", "4": "小雨", "5": "小雪", "6": "雪",
  };
  return map[code] ?? null;
}

/**
 * BAC: レース番組情報 (182バイト/行) - 実データ検証済み
 * 0-1: 場コード(2), 2-3: 年(2), 4-5: 回次(2), 6-7: R番号(2)
 * 8-15: 日付(8), 16-19: 時刻(4), 20-23: 距離(4), 24: 馬場(1)
 * 25: 回り(1), 26-27: 馬場状態(2), 28: 天候(1)
 * 29-30: 種別(2), 31-32: 条件(2), 33-34: 記号(2)
 * 35-84: レース名(50,Shift_JIS), 85-86: 頭数(2)
 */
function importBacFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO races
     (race_id, race_date, venue_code, venue_name, race_number,
      distance, surface, start_time, course_direction, head_count,
      track_condition, weather, grade, race_class, race_name)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 26) continue;

      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      if (!venueCode || !year || isNaN(raceNum)) continue;

      const dateRaw = extractField(line, 8, 8);
      const raceDate = `${dateRaw.slice(0, 4)}-${dateRaw.slice(4, 6)}-${dateRaw.slice(6, 8)}`;
      const timeRaw = extractField(line, 16, 4);
      const startTime = timeRaw.length === 4 ? `${timeRaw.slice(0, 2)}:${timeRaw.slice(2)}` : null;
      const distance = parseInt(extractField(line, 20, 4), 10);
      const surfaceCode = extractField(line, 24, 1);
      const dirCode = extractField(line, 25, 1);

      if (isNaN(distance) || distance === 0) continue;

      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const direction = dirCode === "1" ? "右" : dirCode === "2" ? "左" : "直線";

      // New fields
      const trackCondCode = line.length >= 28 ? extractField(line, 26, 2) : "";
      const trackCondition = parseTrackCondition(trackCondCode);
      const weatherCode = line.length >= 29 ? extractField(line, 28, 1) : "";
      const weather = parseWeather(weatherCode);
      const syubetsu = line.length >= 31 ? extractField(line, 29, 2) : "";
      const jouken = line.length >= 33 ? extractField(line, 31, 2) : "";
      const kigou = line.length >= 35 ? extractField(line, 33, 2) : "";
      const raceName = line.length >= 85 ? extractField(line, 35, 50) : null;
      const headCountStr = line.length >= 87 ? extractField(line, 85, 2) : "";
      const headCount = headCountStr ? parseInt(headCountStr, 10) : null;

      // grade: G1/G2/G3 or OP etc from syubetsu
      const grade = syubetsu === "OP" ? "OP" : (kigou === "13" ? "G3" : kigou === "12" ? "G2" : kigou === "11" ? "G1" : null);
      // race_class: combine syubetsu + jouken
      const raceClass = syubetsu && jouken ? `${syubetsu}/${jouken}` : null;

      stmt.run(
        raceId,
        raceDate,
        venueCode,
        VENUE_CODES[venueCode] ?? venueCode,
        raceNum,
        distance,
        parseSurface(surfaceCode),
        startTime,
        direction,
        isNaN(headCount as number) ? null : headCount,
        trackCondition,
        weather,
        grade,
        raceClass,
        raceName
      );
      count++;
    }
    return count;
  });

  return tx();
}

/**
 * KYI: 競走馬情報 (1022バイト/行) - 実データ検証済み
 * 0-1: 場コード(2), 2-3: 年(2), 4-5: 回次(2), 6-7: R番号(2)
 * 8-9: 馬番(2), 10-17: 血統登録番号(8), 18-47: 馬名(30,Shift_JIS)
 * 171-182: 騎手名(12), 183-185: 斤量(3,10倍値), 187-198: 調教師名(12)
 */
function importKyiFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO entries
     (race_id, horse_number, horse_id, horse_name,
      jockey_name, jockey_code, trainer_name, trainer_code,
      carried_weight, horse_weight, horse_weight_diff, age, sex, gate_number)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 200) continue;

      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      const horseNum = parseInt(extractField(line, 8, 2), 10);
      if (!venueCode || !year || isNaN(raceNum) || isNaN(horseNum)) continue;

      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const horseId = extractField(line, 10, 8);
      const horseName = extractField(line, 18, 30);
      const jockeyName = extractField(line, 171, 12);
      const trainerName = extractField(line, 187, 12);

      // 斤量: 3バイト, 10倍値 (570 = 57.0kg)
      const cwStr = extractField(line, 183, 3);
      const carriedWeight = cwStr ? parseInt(cwStr, 10) / 10 : 0;

      stmt.run(
        raceId,
        horseNum,
        horseId,
        horseName,
        jockeyName,
        null,
        trainerName,
        null,
        carriedWeight,
        null, // horse_weight (直前データTYBから取得)
        null, // weight_diff
        null, // age
        null, // sex
        null  // gate_number
      );
      count++;
    }
    return count;
  });

  return tx();
}

/**
 * SED: 成績データ (374バイト/行) - 実データ検証済み
 * 140-141: 着順(2), 142-146: タイム(5,10倍値), 147-149: 斤量(3,10倍値)
 * 150-157: 騎手名(8), 158-165: 調教師名(8)
 * 174-179: オッズ(6), 180-181: 人気(2)
 * 307-320: コーナー通過順(14, 各コーナー2桁)
 * 332-334: 馬体重(3, kg)
 */
function importSedFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO results
     (race_id, horse_number, horse_id, finish_position, finish_time,
      jockey_name, carried_weight, win_odds, popularity,
      horse_weight, corner_positions)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 173) continue;

      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      const horseNum = parseInt(extractField(line, 8, 2), 10);
      if (!venueCode || !year || isNaN(raceNum) || isNaN(horseNum)) continue;

      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const horseId = extractField(line, 10, 8);

      const fpStr = extractField(line, 140, 2);
      let finishPos: number | null = fpStr ? parseInt(fpStr, 10) : null;
      if (isNaN(finishPos as number)) finishPos = null;

      const timeStr = extractField(line, 142, 5);
      let finishTime: number | null = timeStr ? parseInt(timeStr, 10) / 10 : null;
      if (isNaN(finishTime as number)) finishTime = null;

      const cwStr = extractField(line, 147, 3);
      const carriedWeight = cwStr ? parseInt(cwStr, 10) / 10 : null;

      const jockeyName = extractField(line, 150, 8);

      const oddsStr = extractField(line, 174, 6);
      const winOdds = oddsStr ? parseFloat(oddsStr) : null;

      const popStr = extractField(line, 180, 2);
      let popularity: number | null = popStr ? parseInt(popStr, 10) : null;
      if (isNaN(popularity as number)) popularity = null;

      // Horse weight (pos 332-334, 3 bytes, kg)
      let horseWeight: number | null = null;
      if (line.length >= 335) {
        const hwStr = extractField(line, 332, 3);
        if (hwStr) {
          const hw = parseInt(hwStr, 10);
          if (!isNaN(hw) && hw >= 350 && hw <= 600) horseWeight = hw;
        }
      }

      // Corner positions (pos 307-320, 14 bytes)
      let cornerPositions: string | null = null;
      if (line.length >= 321) {
        const cpRaw = extractField(line, 307, 14);
        if (cpRaw) {
          // Parse as pairs of 2-digit numbers: "13121305" -> "13-12-13-05"
          const corners: string[] = [];
          for (let i = 0; i < cpRaw.length; i += 2) {
            const c = cpRaw.slice(i, i + 2).trim();
            if (c && c !== "00") corners.push(c);
          }
          if (corners.length > 0) cornerPositions = corners.join("-");
        }
      }

      stmt.run(
        raceId,
        horseNum,
        horseId,
        finishPos,
        finishTime,
        jockeyName,
        carriedWeight,
        winOdds,
        popularity,
        horseWeight,
        cornerPositions
      );
      count++;
    }
    return count;
  });

  return tx();
}

/**
 * UKC: 馬基本データ (290バイト/行) - 実データ検証済み
 * 0-7: 血統登録番号(8), 8-43: 馬名(36,Shift_JIS)
 * 44: 性別コード(1, 1=牡 2=牝 3=セ), 45-48: 生年(4)
 * 49-84: 父馬名(36), 85-120: 母馬名(36), 121-156: 母父馬名(36)
 */
function importUkcFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO horses
     (horse_id, horse_name, birth_year, sex, sire, dam, dam_sire, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))`
  );

  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 157) continue;

      const horseId = extractField(line, 0, 8);
      if (!horseId) continue;

      const horseName = extractField(line, 8, 36);

      // 性別
      const sexCode = extractField(line, 44, 1);
      const sex = parseSex(sexCode);

      // 生年
      const birthStr = extractField(line, 45, 4);
      const birthYear = birthStr ? parseInt(birthStr, 10) : null;

      // 血統
      const sire = extractField(line, 49, 36) || null;
      const dam = extractField(line, 85, 36) || null;
      const damSire = extractField(line, 121, 36) || null;

      stmt.run(
        horseId,
        horseName,
        birthYear,
        sex || null,
        sire,
        dam,
        damSire
      );
      count++;
    }
    return count;
  });

  return tx();
}

/**
 * OZ: 基準オッズデータ (955バイト/行) - 実データ検証済み
 * 1行 = 1レース
 * 0-7: レースID（場2+年2+回2+R番号2）, 8-9: 頭数(2)
 * 10-99: 単勝オッズ（18頭 × 5バイト）
 * 100-189: 複勝オッズ（18頭 × 5バイト）
 * 190-954: 馬連オッズ（C(18,2)=153組 × 5バイト）
 */
function importOzFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO odds
     (race_id, bet_type, combination, odds)
     VALUES (?, ?, ?, ?)`
  );

  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 190) continue;

      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      if (!venueCode || !year || isNaN(raceNum)) continue;

      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const headCountStr = extractField(line, 8, 2);
      const headCount = parseInt(headCountStr, 10);
      if (isNaN(headCount) || headCount < 2) continue;

      // 単勝オッズ（pos 10 + i*5, 最大18頭）
      for (let i = 0; i < Math.min(headCount, 18); i++) {
        const oddsStr = extractField(line, 10 + i * 5, 5);
        const odds = oddsStr ? parseFloat(oddsStr) : 0;
        if (odds > 0) {
          stmt.run(raceId, "win", String(i + 1), odds);
          count++;
        }
      }

      // 複勝オッズ（pos 100 + i*5, 最大18頭）
      for (let i = 0; i < Math.min(headCount, 18); i++) {
        const oddsStr = extractField(line, 100 + i * 5, 5);
        const odds = oddsStr ? parseFloat(oddsStr) : 0;
        if (odds > 0) {
          stmt.run(raceId, "place", String(i + 1), odds);
          count++;
        }
      }

      // 馬連オッズ（pos 190+, 18頭固定スロット）
      // 1-2,1-3,...,1-18 (17slots), 2-3,2-4,...,2-18 (16slots), ...
      // 各馬iの開始位置: 190 + (i-1)*(17-(i-2)/2)*5 ではなく
      // 単純に: i番馬の相手jのスロットは (i-1)*17 - (i-1)*(i-2)/2 + (j-i-1) 番目
      for (let i = 1; i <= Math.min(headCount, 18); i++) {
        for (let j = i + 1; j <= 18; j++) {
          // i番馬のブロック開始: 190 + (i-1) * (18-i) * 5 ... ではなく
          // 18頭固定で i番馬のスロット: 17 + 16 + ... の累積
          let slotIdx = 0;
          for (let ii = 1; ii < i; ii++) {
            slotIdx += 18 - ii; // ii番馬は (18-ii)スロット
          }
          slotIdx += j - i - 1;

          const pos = 190 + slotIdx * 5;
          if (pos + 5 > line.length) break;

          if (j > headCount) continue; // 頭数超過はスキップ

          const oddsStr = extractField(line, pos, 5);
          const odds = oddsStr ? parseFloat(oddsStr) : 0;
          if (odds > 0) {
            stmt.run(raceId, "umaren", `${i}-${j}`, odds);
            count++;
          }
        }
      }
    }
    return count;
  });

  return tx();
}

/** 18頭固定スロットの2頭組み合わせインデックス */
function pairSlotIndex(i: number, j: number): number {
  let idx = 0;
  for (let ii = 1; ii < i; ii++) idx += 18 - ii;
  idx += j - i - 1;
  return idx;
}

/** OW: ワイド (778バイト/行, 5バイト/組, 18頭固定C(18,2)=153スロット) */
function importOwFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);
  const stmt = db.prepare(`INSERT OR REPLACE INTO odds (race_id, bet_type, combination, odds) VALUES (?, ?, ?, ?)`);
  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 20) continue;
      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      if (!venueCode || !year || isNaN(raceNum)) continue;
      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const headCount = parseInt(extractField(line, 8, 2), 10);
      if (isNaN(headCount) || headCount < 2) continue;
      for (let i = 1; i <= Math.min(headCount, 18); i++) {
        for (let j = i + 1; j <= Math.min(headCount, 18); j++) {
          const pos = 10 + pairSlotIndex(i, j) * 5;
          if (pos + 5 > line.length) break;
          const oddsStr = extractField(line, pos, 5);
          const odds = oddsStr ? parseFloat(oddsStr) : 0;
          if (odds > 0) { stmt.run(raceId, "wide", `${i}-${j}`, odds); count++; }
        }
      }
    }
    return count;
  });
  return tx();
}

/** OU: 馬単 (1854バイト/行, 6バイト/組, 18×17=306スロット) */
function importOuFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);
  const stmt = db.prepare(`INSERT OR REPLACE INTO odds (race_id, bet_type, combination, odds) VALUES (?, ?, ?, ?)`);
  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 20) continue;
      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      if (!venueCode || !year || isNaN(raceNum)) continue;
      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const headCount = parseInt(extractField(line, 8, 2), 10);
      if (isNaN(headCount) || headCount < 2) continue;
      let slotIdx = 0;
      for (let i = 1; i <= 18; i++) {
        for (let j = 1; j <= 18; j++) {
          if (i === j) continue;
          const pos = 10 + slotIdx * 6;
          slotIdx++;
          if (pos + 6 > line.length) continue;
          if (i > headCount || j > headCount) continue;
          const oddsStr = extractField(line, pos, 6);
          const odds = oddsStr ? parseFloat(oddsStr) : 0;
          if (odds > 0) { stmt.run(raceId, "umatan", `${i}-${j}`, odds); count++; }
        }
      }
    }
    return count;
  });
  return tx();
}

/** OT: 三連複 (4910バイト/行, 6バイト/組, C(18,3)=816スロット) */
function importOtFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);
  const stmt = db.prepare(`INSERT OR REPLACE INTO odds (race_id, bet_type, combination, odds) VALUES (?, ?, ?, ?)`);
  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 20) continue;
      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      if (!venueCode || !year || isNaN(raceNum)) continue;
      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const headCount = parseInt(extractField(line, 8, 2), 10);
      if (isNaN(headCount) || headCount < 3) continue;
      let slotIdx = 0;
      for (let i = 1; i <= 18; i++) {
        for (let j = i + 1; j <= 18; j++) {
          for (let k = j + 1; k <= 18; k++) {
            const pos = 10 + slotIdx * 6;
            slotIdx++;
            if (pos + 6 > line.length) continue;
            if (i > headCount || j > headCount || k > headCount) continue;
            const oddsStr = extractField(line, pos, 6);
            const odds = oddsStr ? parseFloat(oddsStr) : 0;
            if (odds > 0) { stmt.run(raceId, "sanrenpuku", `${i}-${j}-${k}`, odds); count++; }
          }
        }
      }
    }
    return count;
  });
  return tx();
}

/** OV: 三連単 (34286バイト/行, 7バイト/組(10倍値), 18×17×16=4896スロット) */
function importOvFile(filePath: string): number {
  const db = getDb();
  const lines = readFileLines(filePath);
  const stmt = db.prepare(`INSERT OR REPLACE INTO odds (race_id, bet_type, combination, odds) VALUES (?, ?, ?, ?)`);
  const tx = db.transaction(() => {
    let count = 0;
    for (const line of lines) {
      if (line.length < 100) continue;
      const venueCode = extractField(line, 0, 2);
      const year = extractField(line, 2, 2);
      const kai = extractField(line, 4, 2);
      const raceNum = parseInt(extractField(line, 6, 2), 10);
      if (!venueCode || !year || isNaN(raceNum)) continue;
      const raceId = buildRaceId(venueCode, year, kai, raceNum);
      const headCount = parseInt(extractField(line, 8, 2), 10);
      if (isNaN(headCount) || headCount < 3) continue;
      let slotIdx = 0;
      for (let i = 1; i <= 18; i++) {
        for (let j = 1; j <= 18; j++) {
          if (j === i) continue;
          for (let k = 1; k <= 18; k++) {
            if (k === i || k === j) continue;
            const pos = 10 + slotIdx * 7;
            slotIdx++;
            if (pos + 7 > line.length) continue;
            if (i > headCount || j > headCount || k > headCount) continue;
            const oddsStr = extractField(line, pos, 7);
            const oddsRaw = oddsStr ? parseInt(oddsStr, 10) : 0;
            const odds = oddsRaw / 10;
            if (odds > 0) { stmt.run(raceId, "sanrentan", `${i}-${j}-${k}`, odds); count++; }
          }
        }
      }
    }
    return count;
  });
  return tx();
}
