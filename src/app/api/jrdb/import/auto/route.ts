import { NextRequest, NextResponse } from "next/server";
import { getDb, getJrdbDataDir } from "@/lib/jrdb/db";
import fs from "fs";
import path from "path";
import { createUnzip } from "zlib";
import { Readable } from "stream";

/**
 * JRDB自動ダウンロード+インポートAPI
 * POST: 指定日 or 次の開催日のBAC/KYI/OZを自動取得してDBにインポート
 */

const JRDB_FOLDERS: Record<string, string> = {
  BAC: "Bac",
  KYI: "Kyi",
  OZ: "Oz",
};

const VENUE: Record<string, string> = {
  "01": "札幌", "02": "函館", "03": "福島", "04": "新潟",
  "05": "東京", "06": "中山", "07": "中京", "08": "京都",
  "09": "阪神", "10": "小倉",
};

const TRACK: Record<string, string> = {
  "11": "良", "12": "稍重", "13": "重", "14": "不良",
  "21": "良", "22": "稍重", "23": "重", "24": "不良",
};

const WEATHER: Record<string, string> = {
  "1": "晴", "2": "曇", "3": "雨", "4": "小雨", "5": "小雪", "6": "雪",
};

const RUN_STYLES: Record<string, string> = {
  "1": "逃げ", "2": "先行", "3": "差し", "4": "追込",
  "5": "好位差し", "6": "自在", "7": "後方",
};

function getJrdbCredentials(): { user: string; pass: string } | null {
  // .env.local or production .env
  const envPath = path.join(process.cwd(), "scripts", "production", ".env");
  if (!fs.existsSync(envPath)) return null;
  const content = fs.readFileSync(envPath, "utf-8");
  const config: Record<string, string> = {};
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (trimmed && !trimmed.startsWith("#") && trimmed.includes("=")) {
      const [key, ...rest] = trimmed.split("=");
      config[key.trim()] = rest.join("=").trim();
    }
  }
  const user = config.JRDB_USER;
  const pass = config.JRDB_PASS;
  if (!user || !pass) return null;
  return { user, pass };
}

async function downloadJrdbZip(
  user: string,
  pass: string,
  prefix: string,
  dateStr: string
): Promise<Buffer | null> {
  const folder = JRDB_FOLDERS[prefix];
  if (!folder) return null;
  const year = `20${dateStr.slice(0, 2)}`;
  const filename = `${prefix}${dateStr}.zip`;
  const url = `http://www.jrdb.com/member/datazip/${folder}/${year}/${filename}`;

  const auth = Buffer.from(`${user}:${pass}`).toString("base64");
  try {
    const res = await fetch(url, {
      headers: { Authorization: `Basic ${auth}` },
    });
    if (!res.ok || !res.body) return null;
    const arrayBuffer = await res.arrayBuffer();
    const buf = Buffer.from(arrayBuffer);
    if (buf.length < 100) return null;
    return buf;
  } catch {
    return null;
  }
}

function extractZipToDir(zipBuffer: Buffer, prefix: string): number {
  // Use JSZip-like manual ZIP parsing (ZIP is simple enough)
  // Actually, use Node.js built-in approach with AdmZip or manual
  // Since we can't guarantee external deps, use a simple approach
  const targetDir = path.join(getJrdbDataDir(), prefix);
  if (!fs.existsSync(targetDir)) {
    fs.mkdirSync(targetDir, { recursive: true });
  }

  // Simple ZIP extraction using built-in
  // ZIP local file header signature: PK\x03\x04
  let count = 0;
  let offset = 0;
  const buf = zipBuffer;

  while (offset + 30 < buf.length) {
    // Check for local file header
    if (buf.readUInt32LE(offset) !== 0x04034b50) break;

    const compMethod = buf.readUInt16LE(offset + 8);
    const compSize = buf.readUInt32LE(offset + 18);
    const uncompSize = buf.readUInt32LE(offset + 22);
    const nameLen = buf.readUInt16LE(offset + 26);
    const extraLen = buf.readUInt16LE(offset + 28);
    const fileName = buf.toString("ascii", offset + 30, offset + 30 + nameLen);
    const dataStart = offset + 30 + nameLen + extraLen;

    if (fileName.endsWith(".txt") && !fileName.includes("/")) {
      const rawData = buf.subarray(dataStart, dataStart + compSize);

      if (compMethod === 0) {
        // Stored (no compression)
        fs.writeFileSync(path.join(targetDir, fileName), rawData);
        count++;
      } else if (compMethod === 8) {
        // Deflate
        try {
          const { inflateRawSync } = require("zlib");
          const decompressed = inflateRawSync(rawData);
          fs.writeFileSync(path.join(targetDir, fileName), decompressed);
          count++;
        } catch {
          // fallback: write raw
        }
      }
    }

    offset = dataStart + compSize;
  }

  return count;
}

function rd(line: Buffer, pos: number, len: number): string {
  if (pos + len > line.length) return "";
  return line.subarray(pos, pos + len).toString("ascii").replace(/\0/g, "").trim();
}

function rdSjis(line: Buffer, pos: number, len: number): string {
  if (pos + len > line.length) return "";
  try {
    const decoder = new TextDecoder("shift_jis", { fatal: false });
    return decoder.decode(line.subarray(pos, pos + len)).trim().replace(/\u3000/g, " ").trim();
  } catch {
    return "";
  }
}

function importBac(db: ReturnType<typeof getDb>, dateStr: string): number {
  const dir = path.join(getJrdbDataDir(), "BAC");
  if (!fs.existsSync(dir)) return 0;

  let count = 0;
  const files = fs.readdirSync(dir).filter(f => f.startsWith(`BAC${dateStr}`) && f.endsWith(".txt"));

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO races (race_id,race_date,venue_code,venue_name,race_number,distance,surface,start_time,course_direction,track_condition,weather,race_name,grade) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)`
  );

  for (const file of files) {
    const data = fs.readFileSync(path.join(dir, file));
    const lines = data.toString("binary").split("\n");

    for (const rawLine of lines) {
      const line = Buffer.from(rawLine, "binary");
      if (line.length < 26) continue;

      const v = rd(line, 0, 2);
      const y = rd(line, 2, 2);
      const k = rd(line, 4, 2);
      const rn = rd(line, 6, 2);
      if (!v || !y) continue;

      const rid = `${y}${v}${k}${rn}`;
      const dr = rd(line, 8, 8);
      const raceDate = `${dr.slice(0, 4)}-${dr.slice(4, 6)}-${dr.slice(6, 8)}`;
      const dist = parseInt(rd(line, 20, 4)) || 0;
      const sfCode = rd(line, 24, 1);
      const sf = sfCode === "1" ? "芝" : sfCode === "2" ? "ダート" : sfCode === "3" ? "障害" : "?";
      const diCode = rd(line, 25, 1);
      const di = diCode === "1" ? "右" : diCode === "2" ? "左" : diCode === "3" ? "直線" : "右";
      const tc = TRACK[rd(line, 26, 2)] ?? null;
      const w = WEATHER[rd(line, 28, 1)] ?? null;
      const syubetsu = rd(line, 29, 2);
      let nm = rdSjis(line, 35, 50);
      let grade: string | null = null;

      if (nm && nm[0] >= "0" && nm[0] <= "9") {
        const gc = nm[0];
        nm = nm.slice(1).trim();
        grade = gc === "1" ? "G1" : gc === "2" ? "G2" : gc === "3" ? "G3" : syubetsu === "OP" ? "OP" : null;
      } else if (syubetsu === "OP") {
        grade = "OP";
      }

      const tr = rd(line, 16, 4);
      const st = tr.length === 4 ? `${tr.slice(0, 2)}:${tr.slice(2)}` : null;

      stmt.run(rid, raceDate, v, VENUE[v] ?? v, parseInt(rn), dist, sf, st, di, tc, w, nm || null, grade);
      count++;
    }
  }

  return count;
}

function importKyi(db: ReturnType<typeof getDb>, dateStr: string): number {
  const dir = path.join(getJrdbDataDir(), "KYI");
  if (!fs.existsSync(dir)) return 0;

  let count = 0;
  const files = fs.readdirSync(dir).filter(f => f.startsWith(`KYI${dateStr}`) && f.endsWith(".txt"));

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO entries (race_id,horse_number,horse_id,horse_name,jockey_name,trainer_name,carried_weight,idm,rider_index,total_index,run_style,distance_aptitude) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)`
  );

  for (const file of files) {
    const data = fs.readFileSync(path.join(dir, file));
    const lines = data.toString("binary").split("\n");

    for (const rawLine of lines) {
      const line = Buffer.from(rawLine, "binary");
      if (line.length < 200) continue;

      const v = rd(line, 0, 2);
      const y = rd(line, 2, 2);
      const k = rd(line, 4, 2);
      const rn = rd(line, 6, 2);
      const hn = rd(line, 8, 2);
      if (!v || !y || !hn) continue;

      const hnI = parseInt(hn);
      if (isNaN(hnI)) continue;

      const rid = `${y}${v}${k}${rn}`;
      const hid = rd(line, 10, 8);
      const hname = rdSjis(line, 18, 30);
      const jockey = rdSjis(line, 171, 12);
      const trainer = rdSjis(line, 187, 12);
      const cwRaw = rd(line, 183, 3);
      const cw = cwRaw ? parseInt(cwRaw) / 10 : 0;
      const idmRaw = rd(line, 54, 5);
      const idm = idmRaw ? parseFloat(idmRaw) || null : null;
      const riderRaw = rd(line, 59, 5);
      const rider = riderRaw ? parseFloat(riderRaw) || null : null;
      const totalRaw = rd(line, 74, 5);
      const total = totalRaw ? parseFloat(totalRaw) || null : null;
      const rs = RUN_STYLES[rd(line, 85, 1)] ?? null;
      const da = rd(line, 80, 1);

      stmt.run(rid, hnI, hid, hname, jockey, trainer, cw, idm, rider, total, rs, da);
      count++;
    }
  }

  return count;
}

function importOz(db: ReturnType<typeof getDb>, dateStr: string): number {
  const dir = path.join(getJrdbDataDir(), "OZ");
  if (!fs.existsSync(dir)) return 0;

  let count = 0;
  const files = fs.readdirSync(dir).filter(f => f.startsWith(`OZ${dateStr}`) && f.endsWith(".txt"));

  const stmt = db.prepare(
    `INSERT OR REPLACE INTO odds (race_id,bet_type,combination,odds) VALUES (?,?,?,?)`
  );

  for (const file of files) {
    const data = fs.readFileSync(path.join(dir, file));
    const lines = data.toString("binary").split("\n");

    for (const rawLine of lines) {
      const line = Buffer.from(rawLine, "binary");
      if (line.length < 100) continue;

      const v = rd(line, 0, 2);
      const y = rd(line, 2, 2);
      const k = rd(line, 4, 2);
      const rn = rd(line, 6, 2);
      const rid = `${y}${v}${k}${rn}`;
      const headsRaw = rd(line, 8, 2);
      const heads = parseInt(headsRaw) || 18;

      for (let i = 0; i < Math.min(heads, 18); i++) {
        const s = rd(line, 10 + i * 5, 5);
        const o = parseFloat(s);
        if (o > 0) {
          stmt.run(rid, "win", String(i + 1), o);
          count++;
        }
      }
    }
  }

  return count;
}

function getTargetDates(): string[] {
  const now = new Date();
  const dates: string[] = [];

  // 今日と明日
  for (let d = 0; d <= 1; d++) {
    const target = new Date(now.getTime() + d * 86400000);
    const wd = target.getDay(); // 0=Sun, 6=Sat
    if (wd === 0 || wd === 6) {
      const yy = String(target.getFullYear()).slice(2);
      const mm = String(target.getMonth() + 1).padStart(2, "0");
      const dd = String(target.getDate()).padStart(2, "0");
      dates.push(`${yy}${mm}${dd}`);
    }
  }

  // 今日が平日なら次の土曜
  if (dates.length === 0) {
    const wd = now.getDay();
    const daysToSat = (6 - wd + 7) % 7 || 7;
    const sat = new Date(now.getTime() + daysToSat * 86400000);
    const yy = String(sat.getFullYear()).slice(2);
    const mm = String(sat.getMonth() + 1).padStart(2, "0");
    const dd = String(sat.getDate()).padStart(2, "0");
    dates.push(`${yy}${mm}${dd}`);
    // 日曜も
    const sun = new Date(sat.getTime() + 86400000);
    const yy2 = String(sun.getFullYear()).slice(2);
    const mm2 = String(sun.getMonth() + 1).padStart(2, "0");
    const dd2 = String(sun.getDate()).padStart(2, "0");
    dates.push(`${yy2}${mm2}${dd2}`);
  }

  return dates;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const requestedDate = (body as { date?: string }).date;

    const creds = getJrdbCredentials();
    if (!creds) {
      return NextResponse.json(
        { error: "JRDB認証情報が未設定です（scripts/production/.env に JRDB_USER/JRDB_PASS を設定してください）" },
        { status: 400 }
      );
    }

    const db = getDb();
    const results: Array<{
      date: string;
      raceDate: string;
      downloads: Record<string, string>;
      imported: Record<string, number>;
      alreadyExists: boolean;
    }> = [];

    const dates = requestedDate ? [requestedDate] : getTargetDates();

    for (const dateStr of dates) {
      const yy = dateStr.slice(0, 2);
      const mm = dateStr.slice(2, 4);
      const dd = dateStr.slice(4, 6);
      const raceDate = `20${yy}-${mm}-${dd}`;

      // 既にデータがあるかチェック
      const existingRaces = (db.prepare("SELECT COUNT(*) as c FROM races WHERE race_date=?").get(raceDate) as { c: number }).c;
      const existingEntries = (db.prepare("SELECT COUNT(*) as c FROM entries WHERE race_id IN (SELECT race_id FROM races WHERE race_date=?)").get(raceDate) as { c: number }).c;

      if (existingRaces > 0 && existingEntries > 0) {
        results.push({
          date: dateStr,
          raceDate,
          downloads: {},
          imported: { races: existingRaces, entries: existingEntries, note: 0 },
          alreadyExists: true,
        });
        continue;
      }

      // ダウンロード
      const downloads: Record<string, string> = {};
      for (const prefix of ["BAC", "KYI", "OZ"]) {
        const zipData = await downloadJrdbZip(creds.user, creds.pass, prefix, dateStr);
        if (zipData) {
          const count = extractZipToDir(zipData, prefix);
          downloads[prefix] = `${count} files`;
        } else {
          downloads[prefix] = "not available";
        }
      }

      // インポート
      const imported: Record<string, number> = {};
      imported.races = importBac(db, dateStr);
      imported.entries = importKyi(db, dateStr);
      imported.odds = importOz(db, dateStr);

      results.push({ date: dateStr, raceDate, downloads, imported, alreadyExists: false });
    }

    return NextResponse.json({ results });
  } catch (error) {
    console.error("JRDB auto import error:", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "自動インポートに失敗しました" },
      { status: 500 }
    );
  }
}
