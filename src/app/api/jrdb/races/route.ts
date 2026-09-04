import { NextRequest, NextResponse } from "next/server";
import { getRacesByDate } from "@/lib/jrdb/queries";

export async function GET(request: NextRequest) {
  const date = request.nextUrl.searchParams.get("date");
  if (!date) {
    return NextResponse.json({ error: "date parameter is required" }, { status: 400 });
  }

  try {
    const races = getRacesByDate(date);
    return NextResponse.json({ races });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "取得に失敗しました" },
      { status: 500 }
    );
  }
}
