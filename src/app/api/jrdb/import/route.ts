import { NextResponse } from "next/server";
import { importJrdbFiles } from "@/lib/jrdb/import";
import { getDbStats, getImportLog } from "@/lib/jrdb/queries";

export async function POST() {
  try {
    const results = importJrdbFiles();
    const stats = getDbStats();
    return NextResponse.json({ results, stats });
  } catch (error) {
    console.error("JRDB import error:", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "インポートに失敗しました" },
      { status: 500 }
    );
  }
}

export async function GET() {
  try {
    const stats = getDbStats();
    const log = getImportLog();
    return NextResponse.json({ stats, log });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取得に失敗しました" },
      { status: 500 }
    );
  }
}
