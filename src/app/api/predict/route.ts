import Anthropic from "@anthropic-ai/sdk";
import { NextRequest, NextResponse } from "next/server";
import type { RaceInfo } from "@/types";
import {
  scoresToProbabilities,
  blendWithMarket,
  calculateWinEv,
  calculatePoolEv,
  detectSmartMoney,
  adjustProbsWithSmartMoney,
  oddsToMarketProbs,
  diagnoseEvOddsCorrelation,
  type EvResult,
  EV_CONFIG,
} from "@/lib/ev-engine";
import {
  getEntriesByRace,
  getHorseResults,
  getHorse,
  getJockeyStats,
  getTrainerStats,
  checkWeightAlert,
  checkLayoffRisk,
  getRaceById,
  getGateStatsByCourse,
  getSexStatsByCourse,
} from "@/lib/jrdb/queries";

function getClient(apiKey?: string) {
  return new Anthropic({
    apiKey: apiKey || process.env.ANTHROPIC_API_KEY,
  });
}

const SYSTEM_PROMPT = `あなたは競馬予想の専門AIです。レース情報と出馬表データを分析し予想を生成してください。

以下の形式でJSONのみ返してください（マークダウン不要、コードブロック不要）:
{
  "horses": [
    {
      "horseNumber": 馬番(number),
      "horseName": "馬名",
      "aiScore": AI偏差値(number),
      "oddsValue": "A+" | "A" | "B" | "C" | "D",
      "rank": "◎" | "○" | "▲" | "△" | "☆",
      "reason": "予想理由（50文字以内）"
    }
  ],
  "recommendedBets": [
    {
      "betType": "tansho" | "fukusho" | "umaren" | "umatan" | "wide" | "sanrenpuku" | "sanrentan",
      "combinations": ["5", "3-5", "3-5-8" など],
      "confidence": 信頼度(1-5),
      "allocation": 予算配分%(0-100、全betType合計100)
    }
  ],
  "analysis": "レース全体の分析コメント（200文字以内）"
}

■ AI偏差値 — 純粋な馬の強さ（オッズは無関係）
過去成績・血統・騎手力・調教師力・馬場適性・距離適性・馬体重・展開などから総合評価。
- 70以上: 圧倒的実力（GI級）
- 60-69: 重賞クラス
- 50-59: 平均的
- 40-49: やや劣る
- 35-39: 力不足
出走馬全体で正規分布（平均50・標準偏差10）になるよう配分。

■ オッズ歪み(oddsValue) — 実力とオッズの乖離
- A+: 実力に対しオッズが大幅に高い（大穴妙味）
- A: 実力に対しオッズが高い（妙味あり）
- B: 実力とオッズが概ね一致（適正）
- C: 実力に対しオッズがやや低い（やや割高）
- D: 実力に対しオッズが明らかに低い（過大評価、買う価値なし）

■ 予想印（競馬新聞の慣習）
- ◎（本命）: 最も勝つ可能性が高い馬。1頭
- ○（対抗）: 本命に次ぐ実力馬。1-2頭
- ▲（単穴）: 波乱の中心。1-2頭
- △（連下）: 3着以内の可能性。2-3頭
- ☆（穴馬）: 一発の可能性がある大穴。残り

■ 馬券戦略
- oddsValueがA+やAの馬を軸にした買い目を優先
- oddsValueがDの馬を軸にした買い目は避ける
- 全馬券種を出す必要なし。妙味ある馬券種のみ推奨
- allocation（予算配分）は妙味ある買い目に多く配分

■ ルール
- horsesはAI偏差値の高い順にソート
- 馬番のみで表記（馬名は不要）
- JRDBデータがあれば過去成績・血統・騎手/調教師傾向・馬体重変動・枠番傾向・性別傾向を重視
- 馬体重が前走比±10kg以上は注意
- 長期休養明け（3ヶ月以上）はリスク、6ヶ月以上は特に注意`;

function buildJrdbEnrichment(raceId: string): string {
  try {
    const race = getRaceById(raceId);
    const entries = getEntriesByRace(raceId);
    if (entries.length === 0) return "";

    const sections: string[] = ["【JRDB詳細データ】"];

    for (const entry of entries) {
      const lines: string[] = [`\n--- 馬番${entry.horse_number} ${entry.horse_name} ---`];

      // 馬体重
      if (entry.horse_weight) {
        const diffStr = entry.horse_weight_diff
          ? `(${entry.horse_weight_diff > 0 ? "+" : ""}${entry.horse_weight_diff}kg)`
          : "";
        lines.push(`馬体重: ${entry.horse_weight}kg ${diffStr}`);

        // 馬体重アラート
        if (entry.horse_id) {
          const alert = checkWeightAlert(entry.horse_id, entry.horse_weight);
          if (alert && alert.alert !== "normal") {
            lines.push(
              `⚠ 馬体重警告: 前走${alert.previous_weight}kg → 今回${alert.current_weight}kg (${alert.diff > 0 ? "+" : ""}${alert.diff}kg)`
            );
          }
        }
      }

      // 長期休養リスク
      if (entry.horse_id && race) {
        const layoff = checkLayoffRisk(entry.horse_id, race.race_date);
        if (layoff && layoff.risk !== "none") {
          const label = layoff.risk === "high" ? "⚠ 長期休養(高リスク)" : "注意: 休養明け";
          lines.push(
            `${label}: 前走${layoff.last_race_date}（${layoff.days_since_last_race}日前）`
          );
        }
      }

      // 血統
      if (entry.horse_id) {
        const horse = getHorse(entry.horse_id);
        if (horse) {
          const parts: string[] = [];
          if (horse.sire) parts.push(`父:${horse.sire}`);
          if (horse.dam) parts.push(`母:${horse.dam}`);
          if (horse.dam_sire) parts.push(`母父:${horse.dam_sire}`);
          if (parts.length > 0) lines.push(`血統: ${parts.join(" ")}`);
        }
      }

      // 騎手成績
      const jStats = getJockeyStats(entry.jockey_name);
      if (jStats && jStats.total_rides > 0) {
        lines.push(
          `騎手(${entry.jockey_name}): 勝率${jStats.win_rate.toFixed(1)}% 複勝率${jStats.place_rate.toFixed(1)}% (${jStats.total_rides}回騎乗)`
        );
      }

      // 調教師成績
      const tStats = getTrainerStats(entry.trainer_name);
      if (tStats && tStats.total_entries > 0) {
        lines.push(
          `調教師(${entry.trainer_name}): 勝率${tStats.win_rate.toFixed(1)}% 複勝率${tStats.place_rate.toFixed(1)}% (${tStats.total_entries}回出走)`
        );
      }

      // 過去5走
      if (entry.horse_id) {
        const pastResults = getHorseResults(entry.horse_id, 5);
        if (pastResults.length > 0) {
          lines.push("過去成績:");
          for (const r of pastResults) {
            const parts: string[] = [];
            if (r.race_date) parts.push(r.race_date);
            if (r.venue_name) parts.push(r.venue_name);
            if (r.distance && r.surface) parts.push(`${r.surface}${r.distance}m`);
            if (r.track_condition) parts.push(r.track_condition);
            parts.push(`${r.finish_position ?? "?"}着`);
            if (r.last_3f) parts.push(`上がり${r.last_3f}`);
            if (r.horse_weight) {
              const wd = r.horse_weight_diff
                ? `(${r.horse_weight_diff > 0 ? "+" : ""}${r.horse_weight_diff})`
                : "";
              parts.push(`${r.horse_weight}kg${wd}`);
            }
            lines.push(`  ${parts.join(" ")}`);
          }
        }
      }

      sections.push(lines.join("\n"));
    }

    // 枠番傾向
    if (race) {
      const gateStats = getGateStatsByCourse(
        race.venue_code,
        race.surface,
        race.distance
      );
      if (gateStats.length > 0) {
        const gateLines = ["\n【枠番傾向】"];
        for (const g of gateStats) {
          gateLines.push(
            `${g.gate_number}枠: 勝率${g.win_rate.toFixed(1)}% 複勝率${g.place_rate.toFixed(1)}% (${g.total_entries}回出走)`
          );
        }
        sections.push(gateLines.join("\n"));
      }

      // 性別傾向
      const sexStats = getSexStatsByCourse(
        race.venue_code,
        race.surface,
        race.distance
      );
      if (sexStats.length > 0) {
        const sexLines = ["\n【性別傾向】"];
        for (const s of sexStats) {
          sexLines.push(
            `${s.sex}: 勝率${s.win_rate.toFixed(1)}% 複勝率${s.place_rate.toFixed(1)}% (${s.total_entries}回出走)`
          );
        }
        sections.push(sexLines.join("\n"));
      }
    }

    return sections.join("\n");
  } catch {
    return "";
  }
}

export async function POST(request: NextRequest) {
  try {
    const clientApiKey = request.headers.get("x-api-key") || undefined;
    const client = getClient(clientApiKey);
    const { raceInfo, jrdbRaceId } = (await request.json()) as {
      raceInfo: RaceInfo;
      jrdbRaceId?: string;
    };

    const entriesText = raceInfo.entries
      .map(
        (e) =>
          `馬番${e.number} ${e.name} 騎手:${e.jockey} 斤量:${e.weight}kg オッズ:${e.odds}倍 人気:${e.popularity}番人気 ${e.age} 調教師:${e.trainer}`
      )
      .join("\n");

    // JRDBデータがある場合は追加情報を付与
    const jrdbData = jrdbRaceId ? buildJrdbEnrichment(jrdbRaceId) : "";

    const userPrompt = `以下のレースを予想してください。

【レース情報】
${raceInfo.venue} ${raceInfo.raceNumber}R ${raceInfo.name}
${raceInfo.date} ${raceInfo.startTime}
${raceInfo.surface} ${raceInfo.distance}m ${raceInfo.condition}
出走頭数: ${raceInfo.headCount}頭

【出馬表】
${entriesText}
${jrdbData}`;

    const message = await client.messages.create({
      model: "claude-opus-5",
      max_tokens: 8192,
      system: SYSTEM_PROMPT,
      messages: [{ role: "user", content: userPrompt }],
    });

    const textBlock = message.content.find((block) => block.type === "text");
    if (!textBlock || textBlock.type !== "text") {
      return NextResponse.json({ error: "Unexpected response type" }, { status: 500 });
    }

    // マークダウンのコードブロックを除去してJSONをパース
    let jsonText = textBlock.text.trim();
    if (jsonText.startsWith("```")) {
      jsonText = jsonText.replace(/^```(?:json)?\s*\n?/, "").replace(/\n?```\s*$/, "");
    }
    const aiPrediction = JSON.parse(jsonText);

    // --- EV計算エンジンで馬券戦略を数学的に算出 ---
    const aiScores: number[] = aiPrediction.horses.map(
      (h: { aiScore: number }) => h.aiScore
    );
    const odds: number[] = raceInfo.entries.map((e) => e.odds || 0);
    const hasOdds = odds.some((o) => o > 0);

    let evBets: EvResult[] = [];
    let allWinEvs: EvResult[] = [];
    let evData: {
      winProbabilities: number[];
      marketProbabilities: number[];
    } | null = null;

    if (hasOdds && aiScores.length > 0) {
      const modelProbs = scoresToProbabilities(aiScores);
      const marketProbs = oddsToMarketProbs(odds);
      let blendedProbs = blendWithMarket(modelProbs, marketProbs);

      let isEarlyOdds = false;

      if (jrdbRaceId) {
        try {
          const { getDb } = await import("@/lib/jrdb/db");
          const db = getDb();

          const ozRows = db.prepare(
            "SELECT combination, odds FROM odds WHERE race_id = ? AND bet_type = 'win' ORDER BY CAST(combination AS INTEGER)"
          ).all(jrdbRaceId) as { combination: string; odds: number }[];

          if (ozRows.length > 0) {
            const earlyOdds = raceInfo.entries.map((e) => {
              const oz = ozRows.find((r) => parseInt(r.combination) === e.number);
              return oz?.odds ?? 0;
            });

            const matchCount = odds.filter((o, i) =>
              earlyOdds[i] > 0 && Math.abs(o - earlyOdds[i]) < 0.01
            ).length;
            isEarlyOdds = matchCount > odds.filter((o) => o > 0).length * 0.8;

            const signals = detectSmartMoney(earlyOdds, odds);
            blendedProbs = adjustProbsWithSmartMoney(blendedProbs, signals);

            // OZ前日ベースのブレンド確率（全券種EV計算用）
            const piWinEarly = oddsToMarketProbs(earlyOdds);
            const blendForEarly = blendWithMarket(modelProbs, piWinEarly);

            // 全券種EV計算（統一パイプライン: calculatePoolEv）
            const poolBetTypes = [
              { betType: "fukusho", dbType: "place" },
              { betType: "umaren", dbType: "umaren" },
              { betType: "wide", dbType: "wide" },
              { betType: "umatan", dbType: "umatan" },
              { betType: "sanrenpuku", dbType: "sanrenpuku" },
              { betType: "sanrentan", dbType: "sanrentan" },
            ];

            for (const { betType, dbType } of poolBetTypes) {
              const rows = db.prepare(
                "SELECT combination, odds FROM odds WHERE race_id = ? AND bet_type = ?"
              ).all(jrdbRaceId, dbType) as { combination: string; odds: number }[];

              if (rows.length > 0) {
                const poolOdds = new Map(rows.map((r) => [r.combination, r.odds]));
                const poolEvs = calculatePoolEv(betType, blendForEarly, poolOdds, raceInfo.entries.length);
                allWinEvs.push(...poolEvs);
                evBets.push(...poolEvs.filter((r) => r.ev >= EV_CONFIG.evThreshold && !r.isDiagnostic));
              }
            }
          }
        } catch {
          // OZデータ取得失敗は無視
        }
      }

      // 単勝EV（入力オッズ基準）
      const winOddsBasis = isEarlyOdds ? "前日オッズ基準" : "確定オッズ基準";
      const winEvs = calculateWinEv(blendedProbs, odds, winOddsBasis);
      allWinEvs.push(...winEvs);
      evBets.push(...winEvs.filter((r) => r.ev >= EV_CONFIG.evThreshold));
      evBets.sort((a, b) => b.ev - a.ev);

      // 診断: EV-オッズ相関
      const diag = diagnoseEvOddsCorrelation(allWinEvs);
      if (Object.values(diag).some((d) => d.warning)) {
        console.warn("EV-odds correlation warning:", diag);
      }

      evData = {
        winProbabilities: blendedProbs.map((p) => Math.round(p * 1000) / 10),
        marketProbabilities: marketProbs.map((p) => Math.round(p * 1000) / 10),
      };

      // oddsValue
      for (const horse of aiPrediction.horses) {
        const idx = raceInfo.entries.findIndex((e) => e.number === horse.horseNumber);
        if (idx >= 0 && blendedProbs[idx] && marketProbs[idx]) {
          const ratio = blendedProbs[idx] / marketProbs[idx];
          if (ratio >= 2.0) horse.oddsValue = "A+";
          else if (ratio >= 1.3) horse.oddsValue = "A";
          else if (ratio >= 0.8) horse.oddsValue = "B";
          else if (ratio >= 0.5) horse.oddsValue = "C";
          else horse.oddsValue = "D";
        }
      }
    }

    // evLookup: 全計算結果のマップ
    const evLookup: Record<string, number> = {};
    for (const ev of allWinEvs) {
      evLookup[`${ev.betType}:${ev.combination}`] = ev.ev;
    }

    const prediction = {
      ...aiPrediction,
      evBets: evBets.slice(0, 30),
      evData,
      evLookup,
    };

    return NextResponse.json({ prediction });
  } catch (error) {
    console.error("Prediction error:", error);
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "予想生成に失敗しました" },
      { status: 500 }
    );
  }
}
