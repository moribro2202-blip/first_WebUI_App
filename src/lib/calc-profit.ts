import type { BetRecord, BetType } from "@/types";

type RaceOrder = {
  first: number;
  second: number;
  third: number;
};

export function isHit(bet: BetRecord, order: RaceOrder): boolean {
  const { first, second, third } = order;
  const nums = bet.combination.split("-").map(Number);

  switch (bet.betType) {
    case "tansho":
      return nums[0] === first;
    case "fukusho":
      return nums[0] === first || nums[0] === second || nums[0] === third;
    case "umaren": {
      const set = new Set([first, second]);
      return nums.length === 2 && nums.every((n) => set.has(n));
    }
    case "umatan":
      return nums.length === 2 && nums[0] === first && nums[1] === second;
    case "wide": {
      const top3 = new Set([first, second, third]);
      return nums.length === 2 && nums.every((n) => top3.has(n));
    }
    case "sanrenpuku": {
      const set3 = new Set([first, second, third]);
      return nums.length === 3 && nums.every((n) => set3.has(n));
    }
    case "sanrentan":
      return (
        nums.length === 3 &&
        nums[0] === first &&
        nums[1] === second &&
        nums[2] === third
      );
    default:
      return false;
  }
}

export function calcReturn(
  bets: BetRecord[],
  order: RaceOrder,
  payouts: { betType: BetType; amount: number }[]
): { totalBet: number; totalReturn: number; profit: number } {
  const totalBet = bets.reduce((sum, b) => sum + b.amount, 0);
  let totalReturn = 0;

  for (const bet of bets) {
    if (isHit(bet, order)) {
      const payout = payouts.find((p) => p.betType === bet.betType);
      if (payout) {
        // 配当は100円あたりなので、購入金額に応じて計算
        totalReturn += (payout.amount / 100) * bet.amount;
      }
    }
  }

  return { totalBet, totalReturn, profit: totalReturn - totalBet };
}
