/**
 * 期待回収率（EV）計算エンジン v5
 *
 * 修正A: 複数的中プール（複勝K=3, ワイドK=3）の的中総量を正しく扱う
 * 修正B: ブレンド後に全組合計=Kで正規化してからEV計算
 */

// --- Config ---

export const EV_CONFIG = {
  scaleFactor: 0.15,
  alpha: 0.2,
  marketBeta: 1.03,
  lambda2nd: 0.8,
  lambda3rd: 0.6,
  evThreshold: 1.05,
  evCap: 1.5,
  smartMoneyWeight: 0.15,
  smartMoneyWarnThreshold: 0.3,
  paperTrade: true,
  alphaQ: {
    umaren: 0.2, wide: 0.2, umatan: 0.2,
    sanrenpuku: 0.15, sanrentan: 0.1, fukusho: 0.2,
  } as Record<string, number>,
  recommendEnabled: {
    tansho: true, umaren: true, fukusho: true,
    wide: true, umatan: true, sanrenpuku: true, sanrentan: true,
  } as Record<string, boolean>,
  /**
   * OZ基準オッズ → 推定確定オッズの補正係数
   * 公式払戻率 / OZ基準の実測払戻率（データから計算済み）
   */
  /** 2024-2025データから計算した時系列分割補正係数 */
  oddsCorrection: {
    win: 1.082,
    place: 1.151,
    umaren: 1.088,
    wide: 1.160,
    umatan: 1.129,
    sanrenpuku: 1.226,
    sanrentan: 1.275,
  } as Record<string, number>,
};

/** 券種ごとの的中総量K（全組の的中確率の合計値） */
function getWinningOutcomes(betType: string, headCount: number = 18): number {
  switch (betType) {
    case "fukusho": return headCount <= 7 ? 2 : 3;
    case "wide": return 3;
    default: return 1; // tansho, umaren, umatan, sanrenpuku, sanrentan
  }
}

// --- 1. スコア → モデル勝率 ---

export function scoresToProbabilities(aiScores: number[]): number[] {
  const scaled = aiScores.map((s) => (s - 50) * EV_CONFIG.scaleFactor);
  const maxS = Math.max(...scaled);
  const exps = scaled.map((s) => Math.exp(s - maxS));
  const sum = exps.reduce((a, b) => a + b, 0);
  return exps.map((e) => e / sum);
}

// --- 2. 市場確率（β補正） ---

export function oddsToMarketProbs(odds: number[]): number[] {
  const inverses = odds.map((o) => (o > 0 ? 1 / o : 0));
  const sum = inverses.reduce((a, b) => a + b, 0);
  if (sum === 0) return odds.map(() => 1 / odds.length);
  const raw = inverses.map((inv) => inv / sum);
  const powered = raw.map((p) => Math.pow(p, EV_CONFIG.marketBeta));
  const poweredSum = powered.reduce((a, b) => a + b, 0);
  return powered.map((p) => p / poweredSum);
}

// --- 3. 対数線形ブレンド ---

export function blendWithMarket(
  modelProbs: number[], marketProbs: number[], alpha: number = EV_CONFIG.alpha
): number[] {
  const blended = modelProbs.map((mp, i) => {
    const mkt = marketProbs[i];
    if (mp <= 0 || mkt <= 0) return 1e-10;
    return Math.exp(alpha * Math.log(mp) + (1 - alpha) * Math.log(mkt));
  });
  const sum = blended.reduce((a, b) => a + b, 0);
  return blended.map((p) => p / sum);
}

// --- 4. Harville（Stern補正） ---

function conditionalProb2nd(probs: number[], winner: number, candidate: number): number {
  const remaining = probs
    .map((p, i) => (i === winner ? 0 : Math.pow(p, EV_CONFIG.lambda2nd)))
    .reduce((a, b) => a + b, 0);
  if (remaining === 0) return 0;
  return Math.pow(probs[candidate], EV_CONFIG.lambda2nd) / remaining;
}

function conditionalProb3rd(probs: number[], first: number, second: number, candidate: number): number {
  const remaining = probs
    .map((p, i) => (i === first || i === second ? 0 : Math.pow(p, EV_CONFIG.lambda3rd)))
    .reduce((a, b) => a + b, 0);
  if (remaining === 0) return 0;
  return Math.pow(probs[candidate], EV_CONFIG.lambda3rd) / remaining;
}

// --- 5. 券種別Harville確率 ---

export function exactaProb(probs: number[], first: number, second: number): number {
  return probs[first] * conditionalProb2nd(probs, first, second);
}

export function quinellaProb(probs: number[], a: number, b: number): number {
  return exactaProb(probs, a, b) + exactaProb(probs, b, a);
}

export function trifectaProb(probs: number[], first: number, second: number, third: number): number {
  return probs[first] * conditionalProb2nd(probs, first, second) * conditionalProb3rd(probs, first, second, third);
}

export function trioProb(probs: number[], a: number, b: number, c: number): number {
  const perms = [[a,b,c],[a,c,b],[b,a,c],[b,c,a],[c,a,b],[c,b,a]];
  return perms.reduce((sum, [i,j,k]) => sum + trifectaProb(probs, i, j, k), 0);
}

export function wideProb(probs: number[], a: number, b: number): number {
  const n = probs.length;
  let prob = 0;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if (j === i) continue;
      for (let k = 0; k < n; k++) {
        if (k === i || k === j) continue;
        if ([i, j, k].includes(a) && [i, j, k].includes(b)) {
          prob += probs[i] * conditionalProb2nd(probs, i, j) * conditionalProb3rd(probs, i, j, k);
        }
      }
    }
  }
  return prob;
}

export function placeProb(probs: number[], horse: number): number {
  const n = probs.length;
  let prob = 0;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      if (j === i) continue;
      for (let k = 0; k < n; k++) {
        if (k === i || k === j) continue;
        if (horse !== i && horse !== j && horse !== k) continue;
        prob += probs[i] * conditionalProb2nd(probs, i, j) * conditionalProb3rd(probs, i, j, k);
      }
    }
  }
  return prob;
}

// --- Harville関数ディスパッチャ ---

function harvilleCalc(betType: string, probs: number[], indices: number[]): number {
  switch (betType) {
    case "tansho": return probs[indices[0]];
    case "fukusho": return placeProb(probs, indices[0]);
    case "umaren": return quinellaProb(probs, indices[0], indices[1]);
    case "umatan": return exactaProb(probs, indices[0], indices[1]);
    case "wide": return wideProb(probs, indices[0], indices[1]);
    case "sanrenpuku": return trioProb(probs, indices[0], indices[1], indices[2]);
    case "sanrentan": return trifectaProb(probs, indices[0], indices[1], indices[2]);
    default: return 0;
  }
}

function comboToIndices(combo: string): number[] {
  return combo.split("-").map((s) => parseInt(s, 10) - 1);
}

// --- 6. 統一EV計算（修正A+B: K補正 + 正規化） ---

export type EvResult = {
  betType: string;
  combination: string;
  probability: number;
  odds: number;
  ev: number;
  kelly: number;
  warning?: string;
  oddsBasis?: string;
  isDiagnostic?: boolean;
};

/**
 * 全券種共通EV計算（券種プール再ブレンド + K補正 + 正規化 + 払戻率補正）
 *
 * @param useOddsCorrection trueの場合OZ基準オッズを推定確定オッズに補正してEV計算
 */
export function calculatePoolEv(
  betType: string,
  blendedProbs: number[],
  poolOdds: Map<string, number>,
  headCount: number = 18,
  useOddsCorrection: boolean = true
): EvResult[] {
  const alphaQ = EV_CONFIG.alphaQ[betType] ?? 0.2;
  const isRecommend = EV_CONFIG.recommendEnabled[betType] ?? false;
  const K = getWinningOutcomes(betType, headCount);

  // OZ基準オッズ → 推定確定オッズへの補正係数
  const dbBetType = betType === "fukusho" ? "place" : betType === "tansho" ? "win" : betType;
  const correction = useOddsCorrection ? (EV_CONFIG.oddsCorrection[dbBetType] ?? 1.0) : 1.0;

  // Step 1: プール市場確率（K補正、piPoolはOZ基準で計算=確率として正しい）
  let poolTotalInv = 0;
  for (const [, odds] of poolOdds) {
    if (odds > 0) poolTotalInv += 1 / odds;
  }
  if (poolTotalInv === 0) return [];

  // Step 2: 全組の生ブレンド値を計算
  const rawBlends: { combo: string; ozOdds: number; correctedOdds: number; lnQ: number }[] = [];

  for (const [combo, ozOdds] of poolOdds) {
    if (ozOdds <= 0) continue;
    const indices = comboToIndices(combo);
    if (indices.some((idx) => idx < 0 || idx >= blendedProbs.length)) continue;

    const qModel = harvilleCalc(betType, blendedProbs, indices);
    if (qModel <= 0) continue;

    // piPoolはOZ基準で計算（確率の構造は同じ）
    const piPool = K * (1 / ozOdds) / poolTotalInv;
    if (piPool <= 0) continue;

    const lnQ = alphaQ * Math.log(qModel) + (1 - alphaQ) * Math.log(piPool);
    rawBlends.push({ combo, ozOdds, correctedOdds: ozOdds * correction, lnQ });
  }

  if (rawBlends.length === 0) return [];

  // Step 3: 正規化（全組の合計 = K）
  const maxLnQ = Math.max(...rawBlends.map((r) => r.lnQ));
  const expSum = rawBlends.reduce((s, r) => s + Math.exp(r.lnQ - maxLnQ), 0);

  const results: EvResult[] = [];

  for (const r of rawBlends) {
    const qFinal = K * Math.exp(r.lnQ - maxLnQ) / expSum;

    // EVは補正済みオッズ（推定確定オッズ）で計算
    const ev = qFinal * r.correctedOdds;
    const kelly = Math.max(0, (qFinal * r.correctedOdds - 1) / (r.correctedOdds - 1)) / 4;

    const warning = ev > EV_CONFIG.evCap
      ? `過信の疑い（EV=${(ev * 100).toFixed(0)}%）`
      : undefined;

    results.push({
      betType,
      combination: r.combo,
      probability: qFinal,
      odds: r.correctedOdds,
      ev,
      kelly,
      warning,
      oddsBasis: useOddsCorrection ? "推定確定オッズ基準" : "前日オッズ基準",
      isDiagnostic: !isRecommend,
    });
  }

  return results;
}

/**
 * 単勝EV（入力オッズ基準、再ブレンド不要）
 */
export function calculateWinEv(
  blendedProbs: number[], odds: number[], oddsBasis: string = "入力オッズ基準"
): EvResult[] {
  const results: EvResult[] = [];
  for (let i = 0; i < blendedProbs.length; i++) {
    const p = blendedProbs[i];
    const o = odds[i];
    if (!o || o <= 0) continue;
    const ev = p * o;
    const kelly = Math.max(0, (p * o - 1) / (o - 1)) / 4;
    const warning = ev > EV_CONFIG.evCap ? `過信の疑い（EV=${(ev * 100).toFixed(0)}%）` : undefined;
    results.push({
      betType: "tansho", combination: String(i + 1),
      probability: p, odds: o, ev,
      kelly, warning, oddsBasis,
    });
  }
  return results;
}

// --- 7. スマートマネー検出 ---

export type SmartMoneySignal = {
  horseNumber: number; earlyOdds: number; finalOdds: number;
  changeRatio: number;
  signal: "strong_buy" | "buy" | "neutral" | "sell" | "strong_sell";
};

export function detectSmartMoney(earlyOdds: number[], finalOdds: number[]): SmartMoneySignal[] {
  const eI = earlyOdds.map((o) => (o > 0 ? 1/o : 0));
  const eS = eI.reduce((a,b) => a+b, 0);
  const fI = finalOdds.map((o) => (o > 0 ? 1/o : 0));
  const fS = fI.reduce((a,b) => a+b, 0);
  return earlyOdds.map((early, i) => {
    const final = finalOdds[i];
    if (!early || !final || early<=0 || final<=0 || eS===0 || fS===0)
      return { horseNumber:i+1, earlyOdds:early||0, finalOdds:final||0, changeRatio:0, signal:"neutral" as const };
    const m = Math.log((fI[i]/fS)/(eI[i]/eS));
    let signal: SmartMoneySignal["signal"];
    if (m>0.2) signal="strong_buy"; else if (m>0.05) signal="buy";
    else if (m>-0.05) signal="neutral"; else if (m>-0.2) signal="sell";
    else signal="strong_sell";
    return { horseNumber:i+1, earlyOdds:early, finalOdds:final, changeRatio:m, signal };
  });
}

export function adjustProbsWithSmartMoney(
  probs: number[], signals: SmartMoneySignal[], weight: number = EV_CONFIG.smartMoneyWeight
): number[] {
  const adj = probs.map((p,i) => { const s=signals[i]; return s ? p*Math.exp(s.changeRatio*weight) : p; });
  const sum = adj.reduce((a,b)=>a+b,0);
  return adj.map((p)=>p/sum);
}

// --- 8. 予算配分 ---

export type BetAllocation = {
  betType: string; combination: string; ev: number;
  probability: number; odds: number; amount: number; kellyFraction: number;
};

export function allocateBudget(evResults: EvResult[], budget: number): BetAllocation[] {
  const q = evResults.filter((r) => r.ev>=EV_CONFIG.evThreshold && r.kelly>0 && !r.isDiagnostic);
  if (q.length===0) return [];
  const raw = q.map((r) => ({...r, rawAmount: budget*r.kelly}));
  const tot = raw.reduce((s,r) => s+r.rawAmount, 0);
  const sc = tot>budget ? budget/tot : 1.0;
  return raw.map((r) => ({
    betType:r.betType, combination:r.combination, ev:r.ev,
    probability:r.probability, odds:r.odds,
    amount: Math.max(100, Math.round((r.rawAmount*sc)/100)*100),
    kellyFraction: r.kelly,
  }));
}

// --- 9. 診断 ---

export function diagnoseEvOddsCorrelation(
  evResults: EvResult[]
): Record<string, { slope: number; warning: boolean }> {
  const byType = new Map<string, { lnOdds: number; lnEv: number }[]>();
  for (const r of evResults) {
    if (r.odds<=0 || r.ev<=0) continue;
    const arr = byType.get(r.betType) ?? [];
    arr.push({ lnOdds: Math.log(r.odds), lnEv: Math.log(r.ev) });
    byType.set(r.betType, arr);
  }
  const result: Record<string, { slope: number; warning: boolean }> = {};
  for (const [bt, pts] of byType) {
    if (pts.length<3) continue;
    const n=pts.length;
    const mx=pts.reduce((s,p)=>s+p.lnOdds,0)/n;
    const my=pts.reduce((s,p)=>s+p.lnEv,0)/n;
    let num=0, den=0;
    for (const p of pts) { num+=(p.lnOdds-mx)*(p.lnEv-my); den+=(p.lnOdds-mx)**2; }
    const slope = den>0 ? num/den : 0;
    result[bt] = { slope, warning: Math.abs(slope)>0.2 };
  }
  return result;
}
