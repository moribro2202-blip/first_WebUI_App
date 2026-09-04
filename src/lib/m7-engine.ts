/**
 * M7 Full Combined 予測エンジン
 *
 * v25: Stern補正(λ1=0.9, λ2=0.8) + PredBlend≤8フィルタ
 * 外部監査（Fable5）対応済み。モデル凍結版。
 */

import { getDb } from "./jrdb/db";

// --- 凍結パラメータ（変更禁止） ---

const M7_CONFIG = {
  alpha: 0.5,
  scaleFactor: 0.15,
  marketBeta: 1.03,
  lambda1: 0.9,   // Stern 2着補正
  lambda2: 0.8,   // Stern 3着補正
  takeout: 0.75,  // 三連複控除率
  predBlendThreshold: 8,
  maxTrioOdds: 500,
} as const;

// --- Types ---

export type M7HorseScore = {
  horseNumber: number;
  horseId: string;
  horseName: string;
  jockeyName: string;
  idm: number;
  riderIndex: number;
  runStyle: string | null;
  trackFit: number;
  weightStability: number;
  distanceFit: number;
  surfaceFit: number;
  totalScore: number;
  modelProb: number;
  marketProb: number;
  blendedProb: number;
};

export type M7Prediction = {
  raceId: string;
  raceDate: string;
  venueName: string;
  raceNumber: number;
  distance: number;
  surface: string;
  trackCondition: string | null;
  headCount: number;
  horses: M7HorseScore[];
  top3: number[];           // horse numbers
  trioProb: number;         // Stern-corrected Harville
  predBlend: number;        // predicted trio odds
  shouldBet: boolean;       // PredBlend <= threshold
  combination: string;      // "1-3-5" format
};

// --- 1. Score Calculation ---

type TrainingData = {
  jockeyStats: Map<string, { races: number; wins: number }>;
  horseHistory: Map<string, Array<{
    fp: number; dist: number; surface: string; venue: string;
    weightDiff: number | null;
  }>>;
  trackPerf: Map<string, Map<string, number[]>>;  // horseId -> trackCond -> [fp]
};

function buildTrainingData(beforeDate: string): TrainingData {
  const db = getDb();
  const oneYearAgo = new Date(beforeDate);
  oneYearAgo.setFullYear(oneYearAgo.getFullYear() - 1);
  const startDate = oneYearAgo.toISOString().slice(0, 10);

  const jockeyStats = new Map<string, { races: number; wins: number }>();
  const horseHistory = new Map<string, TrainingData["horseHistory"] extends Map<string, infer V> ? V : never>();
  const trackPerf = new Map<string, Map<string, number[]>>();

  const rows = db.prepare(`
    SELECT r.race_id, r.horse_number, r.finish_position, r.horse_id, r.horse_weight_diff,
           e.jockey_name, ra.distance, ra.surface, ra.venue_code, ra.track_condition
    FROM results r
    JOIN entries e ON r.race_id = e.race_id AND r.horse_number = e.horse_number
    JOIN races ra ON r.race_id = ra.race_id
    WHERE ra.race_date >= ? AND ra.race_date < ?
    AND r.finish_position IS NOT NULL
    ORDER BY ra.race_date
  `).all(startDate, beforeDate) as Array<{
    race_id: string; horse_number: number; finish_position: number;
    horse_id: string; horse_weight_diff: number | null;
    jockey_name: string; distance: number; surface: string;
    venue_code: string; track_condition: string | null;
  }>;

  for (const row of rows) {
    // Jockey stats
    if (row.jockey_name) {
      const js = jockeyStats.get(row.jockey_name) ?? { races: 0, wins: 0 };
      js.races++;
      if (row.finish_position === 1) js.wins++;
      jockeyStats.set(row.jockey_name, js);
    }

    // Horse history
    if (row.horse_id) {
      const hist = horseHistory.get(row.horse_id) ?? [];
      hist.push({
        fp: row.finish_position,
        dist: row.distance,
        surface: row.surface,
        venue: row.venue_code,
        weightDiff: row.horse_weight_diff,
      });
      if (hist.length > 30) hist.splice(0, hist.length - 30);
      horseHistory.set(row.horse_id, hist);

      // Track condition performance
      if (row.track_condition) {
        let htp = trackPerf.get(row.horse_id);
        if (!htp) { htp = new Map(); trackPerf.set(row.horse_id, htp); }
        const arr = htp.get(row.track_condition) ?? [];
        arr.push(row.finish_position);
        htp.set(row.track_condition, arr);
      }
    }
  }

  return { jockeyStats, horseHistory, trackPerf };
}

function computeM7Score(
  horseNumber: number,
  raceId: string,
  venueCode: string,
  surface: string,
  distance: number,
  trackCondition: string | null,
  entry: {
    horseId: string; jockeyName: string;
    idm: number | null; riderIndex: number | null; runStyle: string | null;
  },
  training: TrainingData,
): { score: number; trackFit: number; weightStability: number; distanceFit: number; surfaceFit: number } {
  // Base: IDM
  const base = (entry.idm && entry.idm > 0) ? entry.idm : 50;

  // Rider index from TYB
  const riderB = (entry.riderIndex && entry.riderIndex > 0) ? entry.riderIndex : 0;

  // Track condition fitness
  let trackFit = 0;
  if (entry.horseId && trackCondition) {
    const htp = training.trackPerf.get(entry.horseId);
    if (htp) {
      const tcResults = htp.get(trackCondition);
      if (tcResults && tcResults.length >= 3) {
        const avg = tcResults.reduce((a, b) => a + b, 0) / tcResults.length;
        trackFit = (6 - avg) * 1.5;
      }
    }
  }

  // Run style bonus
  const rsBonus: Record<string, number> = {
    '逃げ': 1.0, '先行': 0.5, '好位差し': 0.3, '差し': 0,
    '追込': -0.3, '自在': 0.3, '後方': -0.5,
  };
  const runStyleB = entry.runStyle ? (rsBonus[entry.runStyle] ?? 0) : 0;

  // Weight stability
  let weightStability = 0;
  if (entry.horseId) {
    const hist = training.horseHistory.get(entry.horseId);
    if (hist) {
      const recentW = hist.slice(-3).filter(h => h.weightDiff !== null);
      if (recentW.length > 0) {
        const lastDiff = recentW[recentW.length - 1].weightDiff!;
        if (Math.abs(lastDiff) > 10) weightStability = -1.5;
        else if (Math.abs(lastDiff) <= 4) weightStability = 0.5;
      }
    }
  }

  // Distance & surface fit
  let distanceFit = 0;
  let surfaceFit = 0;
  if (entry.horseId) {
    const hist = training.horseHistory.get(entry.horseId);
    if (hist) {
      const distRaces = hist.filter(h => h.dist && Math.abs(h.dist - distance) <= 200);
      if (distRaces.length >= 2) {
        const recent = distRaces.slice(-5);
        distanceFit = (6 - recent.reduce((a, r) => a + r.fp, 0) / recent.length) * 0.8;
      }
      const surfRaces = hist.filter(h => h.surface === surface);
      if (surfRaces.length >= 2) {
        const recent = surfRaces.slice(-5);
        surfaceFit = (6 - recent.reduce((a, r) => a + r.fp, 0) / recent.length) * 0.8;
      }
    }
  }

  return {
    score: base + riderB + trackFit + runStyleB + weightStability + distanceFit + surfaceFit,
    trackFit, weightStability, distanceFit, surfaceFit,
  };
}

// --- 2. Probability Functions ---

function softmax(scores: number[]): number[] {
  const scaled = scores.map(s => (s - 50) * M7_CONFIG.scaleFactor);
  const mx = Math.max(...scaled);
  const exps = scaled.map(s => Math.exp(s - mx));
  const sum = exps.reduce((a, b) => a + b, 0);
  return exps.map(e => e / sum);
}

function marketProbs(odds: number[]): number[] {
  const inv = odds.map(o => o > 0 ? 1 / o : 0);
  const sum = inv.reduce((a, b) => a + b, 0);
  if (sum === 0) return odds.map(() => 1 / odds.length);
  const raw = inv.map(i => i / sum);
  const pw = raw.map(p => Math.pow(p, M7_CONFIG.marketBeta));
  const pwSum = pw.reduce((a, b) => a + b, 0);
  return pw.map(p => p / pwSum);
}

function blend(model: number[], market: number[]): number[] {
  const alpha = M7_CONFIG.alpha;
  const bl = model.map((mp, i) => {
    const mkt = market[i];
    if (mp <= 0 || mkt <= 0) return 1e-10;
    return Math.exp(alpha * Math.log(mp) + (1 - alpha) * Math.log(mkt));
  });
  const sum = bl.reduce((a, b) => a + b, 0);
  return bl.map(p => p / sum);
}

// --- 3. Stern-corrected Harville ---

function sternTrioProb(probs: number[], i: number, j: number, k: number): number {
  const { lambda1, lambda2 } = M7_CONFIG;
  const perms = [[i,j,k],[i,k,j],[j,i,k],[j,k,i],[k,i,j],[k,j,i]];
  let total = 0;
  for (const [a, b, c] of perms) {
    const s = probs.reduce((x, y) => x + y, 0);
    if (s <= 0) return 0;
    const p1 = probs[a] / s;

    // 2nd: lambda1 correction
    const rem2 = probs.map((p, idx) => idx === a ? 0 : Math.pow(p, lambda1));
    const s2 = rem2.reduce((x, y) => x + y, 0);
    if (s2 <= 0) return 0;
    const p2 = rem2[b] / s2;

    // 3rd: lambda2 correction
    const rem3 = probs.map((p, idx) => (idx === a || idx === b) ? 0 : Math.pow(p, lambda2));
    const s3 = rem3.reduce((x, y) => x + y, 0);
    if (s3 <= 0) return 0;
    const p3 = rem3[c] / s3;

    total += p1 * p2 * p3;
  }
  return total;
}

// --- 4. Main Prediction Function ---

export function predictRace(raceId: string): M7Prediction | null {
  const db = getDb();

  // Load race info
  const race = db.prepare("SELECT * FROM races WHERE race_id = ?").get(raceId) as {
    race_id: string; race_date: string; venue_code: string; venue_name: string;
    race_number: number; distance: number; surface: string;
    track_condition: string | null; head_count: number | null;
  } | undefined;
  if (!race) return null;

  // Load entries with IDM
  const entries = db.prepare(`
    SELECT horse_number, horse_id, horse_name, jockey_name,
           idm, rider_index, total_index, run_style
    FROM entries WHERE race_id = ? ORDER BY horse_number
  `).all(raceId) as Array<{
    horse_number: number; horse_id: string; horse_name: string; jockey_name: string;
    idm: number | null; rider_index: number | null; total_index: number | null;
    run_style: string | null;
  }>;
  if (entries.length < 5) return null;

  // Load win odds (OZ)
  const ozRows = db.prepare(
    "SELECT combination, odds FROM odds WHERE race_id = ? AND bet_type = 'win'"
  ).all(raceId) as Array<{ combination: string; odds: number }>;
  if (ozRows.length < 5) return null;
  const winOdds = new Map<number, number>();
  for (const r of ozRows) winOdds.set(parseInt(r.combination), r.odds);

  // Build training data
  const training = buildTrainingData(race.race_date);

  // Compute scores
  const horseNumbers = entries.map(e => e.horse_number).filter(hn => winOdds.has(hn));
  if (horseNumbers.length < 5) return null;

  const horseScores: M7HorseScore[] = [];
  const scores: number[] = [];
  const odds: number[] = [];

  for (const hn of horseNumbers) {
    const entry = entries.find(e => e.horse_number === hn)!;
    const result = computeM7Score(
      hn, raceId, race.venue_code, race.surface, race.distance,
      race.track_condition,
      { horseId: entry.horse_id, jockeyName: entry.jockey_name,
        idm: entry.idm, riderIndex: entry.rider_index, runStyle: entry.run_style },
      training,
    );
    scores.push(result.score);
    odds.push(winOdds.get(hn)!);
    horseScores.push({
      horseNumber: hn,
      horseId: entry.horse_id,
      horseName: entry.horse_name,
      jockeyName: entry.jockey_name,
      idm: entry.idm ?? 50,
      riderIndex: entry.rider_index ?? 0,
      runStyle: entry.run_style,
      trackFit: result.trackFit,
      weightStability: result.weightStability,
      distanceFit: result.distanceFit,
      surfaceFit: result.surfaceFit,
      totalScore: result.score,
      modelProb: 0,
      marketProb: 0,
      blendedProb: 0,
    });
  }

  // Probabilities
  const mp = softmax(scores);
  const mkp = marketProbs(odds);
  const bp = blend(mp, mkp);

  for (let i = 0; i < horseScores.length; i++) {
    horseScores[i].modelProb = mp[i];
    horseScores[i].marketProb = mkp[i];
    horseScores[i].blendedProb = bp[i];
  }

  // Top 3
  const ranked = horseScores
    .map((h, i) => ({ idx: i, prob: bp[i], hn: h.horseNumber }))
    .sort((a, b) => b.prob - a.prob);
  const top3 = ranked.slice(0, 3).map(r => r.hn).sort((a, b) => a - b);
  const top3Indices = ranked.slice(0, 3).map(r => r.idx);

  // Stern Harville trio probability
  const trioProb = sternTrioProb(bp, top3Indices[0], top3Indices[1], top3Indices[2]);
  const predBlend = trioProb > 0 ? (1 / trioProb) * M7_CONFIG.takeout : 9999;

  // Sort horses by blended prob desc
  horseScores.sort((a, b) => b.blendedProb - a.blendedProb);

  return {
    raceId,
    raceDate: race.race_date,
    venueName: race.venue_name,
    raceNumber: race.race_number,
    distance: race.distance,
    surface: race.surface,
    trackCondition: race.track_condition,
    headCount: race.head_count ?? entries.length,
    horses: horseScores,
    top3,
    trioProb,
    predBlend,
    shouldBet: predBlend <= M7_CONFIG.predBlendThreshold,
    combination: top3.join("-"),
  };
}

// --- 5. Batch Prediction for a Date ---

export function predictDate(date: string): M7Prediction[] {
  const db = getDb();
  const races = db.prepare(
    "SELECT race_id FROM races WHERE race_date = ? ORDER BY venue_code, race_number"
  ).all(date) as Array<{ race_id: string }>;

  const predictions: M7Prediction[] = [];
  for (const { race_id } of races) {
    const pred = predictRace(race_id);
    if (pred) predictions.push(pred);
  }
  return predictions;
}

// --- 6. Export config for display ---

export const M7_DISPLAY_CONFIG = {
  ...M7_CONFIG,
  modelName: "M7 Full Combined",
  version: "v25",
  features: ["IDM", "騎手指数", "馬場適性", "脚質", "体重安定性", "距離適性", "馬場適性"],
  filterDescription: "PredBlend ≤ 8 (Stern補正済み予想三連複オッズ8倍以下)",
} as const;
