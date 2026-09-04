import { NextResponse } from "next/server";
import { predictDate, predictRace } from "@/lib/m7-engine";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const date = searchParams.get("date");
  const raceId = searchParams.get("raceId");

  if (raceId) {
    const prediction = predictRace(raceId);
    if (!prediction) {
      return NextResponse.json({ error: "Race not found or insufficient data" }, { status: 404 });
    }
    return NextResponse.json(prediction);
  }

  if (date) {
    const predictions = predictDate(date);
    return NextResponse.json({
      date,
      total: predictions.length,
      shouldBet: predictions.filter(p => p.shouldBet).length,
      predictions,
    });
  }

  return NextResponse.json({ error: "date or raceId parameter required" }, { status: 400 });
}
