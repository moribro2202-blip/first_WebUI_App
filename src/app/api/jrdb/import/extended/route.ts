import { NextRequest, NextResponse } from "next/server";
import { getDb, getJrdbDataDir } from "@/lib/jrdb/db";
import { importJrdbFiles } from "@/lib/jrdb/import";
import fs from "fs";
import path from "path";

/**
 * 拡張インポートAPI
 * POST: 1) ZIPを解凍 2) 標準インポート 3) 拡張フィールド（IDM等）をPythonで更新
 */

// Simple ZIP extraction using Node.js built-in (requires unzip command)
async function extractZips(sourceDir: string): Promise<{ extracted: number; errors: string[] }> {
  const jrdbDir = getJrdbDataDir();
  let extracted = 0;
  const errors: string[] = [];

  if (!fs.existsSync(sourceDir)) {
    return { extracted: 0, errors: [`Directory not found: ${sourceDir}`] };
  }

  const zipFiles = fs.readdirSync(sourceDir).filter(f => f.endsWith('.zip'));

  for (const zipFile of zipFiles) {
    // Determine target directory from filename prefix
    let targetSubdir = "";
    for (const prefix of ["TYB", "KYI", "CHA", "BAC", "SED", "UKC", "OZ", "OT", "OW", "OU", "OV"]) {
      if (zipFile.toUpperCase().startsWith(prefix)) {
        targetSubdir = prefix;
        break;
      }
    }
    if (!targetSubdir) continue;

    const targetDir = path.join(jrdbDir, targetSubdir);
    fs.mkdirSync(targetDir, { recursive: true });

    try {
      // Use AdmZip-like approach with built-in zlib
      const { execSync } = require("child_process");
      const zipPath = path.join(sourceDir, zipFile);

      // PowerShell to extract (Windows compatible)
      execSync(
        `powershell -Command "Expand-Archive -Path '${zipPath}' -DestinationPath '${targetDir}' -Force"`,
        { timeout: 30000 }
      );
      extracted++;
    } catch (e) {
      errors.push(`${zipFile}: ${e instanceof Error ? e.message : "extract error"}`);
    }
  }

  return { extracted, errors };
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json().catch(() => ({}));
    const sourceDir = body.sourceDir || "C:\\Users\\moribro2201\\Downloads\\data";

    // Step 1: Extract ZIPs
    const zipResult = await extractZips(sourceDir);

    // Step 2: Standard import (BAC, KYI, SED, UKC, OZ, etc.)
    const importResults = importJrdbFiles();
    const importSummary: Record<string, { success: number; records: number }> = {};
    for (const r of importResults) {
      if (!importSummary[r.type]) importSummary[r.type] = { success: 0, records: 0 };
      if (r.status === "success") {
        importSummary[r.type].success++;
        importSummary[r.type].records += r.records;
      }
    }

    // Step 3: Update extended fields (IDM, run_style, track_condition, etc.)
    const db = getDb();
    const jrdbDir = getJrdbDataDir();

    // Update BAC extended fields
    let bacUpdated = 0;
    const bacDir = path.join(jrdbDir, "BAC");
    if (fs.existsSync(bacDir)) {
      const TRACK_COND: Record<string, string> = {
        "11":"良","12":"稍重","13":"重","14":"不良",
        "21":"良","22":"稍重","23":"重","24":"不良",
      };
      const WEATHER: Record<string, string> = {
        "1":"晴","2":"曇","3":"雨","4":"小雨","5":"小雪","6":"雪",
      };

      const bacFiles = fs.readdirSync(bacDir).filter(f => f.endsWith('.txt'));
      const bacStmt = db.prepare(`
        UPDATE races SET track_condition=?, weather=?, race_name=COALESCE(?,race_name)
        WHERE race_id=?
      `);

      for (const file of bacFiles) {
        const lines = fs.readFileSync(path.join(bacDir, file));
        let offset = 0;
        while (offset < lines.length) {
          const lineEnd = lines.indexOf(0x0a, offset);
          const end = lineEnd === -1 ? lines.length : lineEnd;
          const line = lines.subarray(offset, end);
          offset = end + 1;
          if (line.length < 87) continue;

          const venue = line.subarray(0, 2).toString('ascii').trim();
          const year = line.subarray(2, 4).toString('ascii').trim();
          const kai = line.subarray(4, 6).toString('ascii').trim();
          const raceNum = line.subarray(6, 8).toString('ascii').trim();
          if (!venue || !year || !raceNum) continue;
          const raceId = `${year}${venue}${kai}${raceNum}`;

          const tcCode = line.subarray(26, 28).toString('ascii').trim();
          const wCode = line.subarray(28, 29).toString('ascii').trim();
          const trackCond = TRACK_COND[tcCode] ?? null;
          const weather = WEATHER[wCode] ?? null;

          let raceName: string | null = null;
          try {
            const nameBytes = line.subarray(35, 85);
            const iconv = require('iconv-lite');
            raceName = iconv.decode(Buffer.from(nameBytes), 'shift_jis').trim() || null;
          } catch { /* skip */ }

          bacStmt.run(trackCond, weather, raceName, raceId);
          bacUpdated++;
        }
      }
    }

    // Update TYB extended fields (IDM, rider_index)
    let tybUpdated = 0;
    const tybDir = path.join(jrdbDir, "TYB");
    if (fs.existsSync(tybDir)) {
      const tybFiles = fs.readdirSync(tybDir).filter(f => f.endsWith('.txt'));
      const tybStmt = db.prepare(`
        UPDATE entries SET idm=COALESCE(?,idm), rider_index=COALESCE(?,rider_index),
        total_index=COALESCE(?,total_index) WHERE race_id=? AND horse_number=?
      `);

      for (const file of tybFiles) {
        const buf = fs.readFileSync(path.join(tybDir, file));
        let offset = 0;
        while (offset < buf.length) {
          const lineEnd = buf.indexOf(0x0a, offset);
          const end = lineEnd === -1 ? buf.length : lineEnd;
          const line = buf.subarray(offset, end);
          offset = end + 1;
          if (line.length < 50) continue;

          const venue = line.subarray(0, 2).toString('ascii').trim();
          const year = line.subarray(2, 4).toString('ascii').trim();
          const kai = line.subarray(4, 6).toString('ascii').trim();
          const raceNum = line.subarray(6, 8).toString('ascii').trim();
          const hn = parseInt(line.subarray(8, 10).toString('ascii').trim(), 10);
          if (!venue || !year || isNaN(hn)) continue;
          const raceId = `${year}${venue}${kai}${raceNum}`;

          const idm = parseFloat(line.subarray(10, 15).toString('ascii').trim()) || null;
          const rider = parseFloat(line.subarray(15, 20).toString('ascii').trim()) || null;
          const total = parseFloat(line.subarray(40, 45).toString('ascii').trim()) || null;

          tybStmt.run(idm, rider, total, raceId, hn);
          tybUpdated++;
        }
      }
    }

    // Get final DB stats
    const finalStats = {
      races: (db.prepare("SELECT COUNT(*) as c FROM races").get() as { c: number }).c,
      entries: (db.prepare("SELECT COUNT(*) as c FROM entries").get() as { c: number }).c,
      results: (db.prepare("SELECT COUNT(*) as c FROM results").get() as { c: number }).c,
      withIdm: (db.prepare("SELECT COUNT(*) as c FROM entries WHERE idm IS NOT NULL").get() as { c: number }).c,
      withTrackCond: (db.prepare("SELECT COUNT(*) as c FROM races WHERE track_condition IS NOT NULL").get() as { c: number }).c,
    };

    return NextResponse.json({
      zipExtracted: zipResult.extracted,
      zipErrors: zipResult.errors,
      importSummary,
      bacUpdated,
      tybUpdated,
      dbStats: finalStats,
    });
  } catch (error) {
    console.error("Extended import error:", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "インポートに失敗" },
      { status: 500 }
    );
  }
}
