import type { RaceResult, BetType, PerformanceStats, BetRecord } from "@/types";
import { BET_TYPE_LABELS } from "@/types";
import { isHit } from "./calc-profit";

export function calcPerformanceStats(results: RaceResult[]): PerformanceStats[] {
  const betTypes: BetType[] = [
    "tansho", "fukusho", "umaren", "umatan", "wide", "sanrenpuku", "sanrentan",
  ];

  return betTypes.map((betType) => {
    let totalBets = 0;
    let wins = 0;
    let totalBetAmount = 0;
    let totalReturnAmount = 0;

    for (const result of results) {
      const betsOfType = result.bets.filter((b) => b.betType === betType);
      if (betsOfType.length === 0) continue;

      for (const bet of betsOfType) {
        totalBets++;
        totalBetAmount += bet.amount;

        const order = { first: result.first, second: result.second, third: result.third };
        if (isHit(bet, order)) {
          wins++;
          const payout = result.payouts.find((p) => p.betType === betType);
          if (payout) {
            totalReturnAmount += (payout.amount / 100) * bet.amount;
          }
        }
      }
    }

    return {
      betType,
      totalBets,
      wins,
      hitRate: totalBets > 0 ? (wins / totalBets) * 100 : 0,
      totalBetAmount,
      totalReturnAmount,
      recoveryRate: totalBetAmount > 0 ? (totalReturnAmount / totalBetAmount) * 100 : 0,
    };
  });
}

export function calcOverallStats(results: RaceResult[]) {
  const totalPredictions = results.length;
  const totalBet = results.reduce((s, r) => s + r.totalBet, 0);
  const totalReturn = results.reduce((s, r) => s + r.totalReturn, 0);
  const profit = totalReturn - totalBet;
  const recoveryRate = totalBet > 0 ? (totalReturn / totalBet) * 100 : 0;

  // 1レースでも的中があればhit
  const hitRaces = results.filter((r) => r.totalReturn > 0).length;
  const hitRate = totalPredictions > 0 ? (hitRaces / totalPredictions) * 100 : 0;

  return { totalPredictions, totalBet, totalReturn, profit, recoveryRate, hitRate };
}
