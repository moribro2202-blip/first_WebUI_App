export type RaceType = "central" | "local";

export type BetType =
  | "tansho"
  | "fukusho"
  | "umaren"
  | "umatan"
  | "wide"
  | "sanrenpuku"
  | "sanrentan";

export const BET_TYPE_LABELS: Record<BetType, string> = {
  tansho: "単勝",
  fukusho: "複勝",
  umaren: "馬連",
  umatan: "馬単",
  wide: "ワイド",
  sanrenpuku: "三連複",
  sanrentan: "三連単",
};

export type AiRank = "◎" | "○" | "▲" | "△" | "☆";

export type HorseEntry = {
  number: number;
  name: string;
  jockey: string;
  weight: number;
  odds: number;
  popularity: number;
  age: string;
  trainer: string;
};

export type RaceInfo = {
  id: string;
  date: string;
  venue: string;
  raceNumber: number;
  name: string;
  type: RaceType;
  distance: number;
  surface: string;
  condition: string;
  headCount: number;
  startTime: string;
  entries: HorseEntry[];
};

export type PredictionHorse = {
  horseNumber: number;
  horseName: string;
  aiScore: number;
  rank: AiRank;
  reason: string;
};

export type RecommendedBet = {
  betType: BetType;
  combinations: string[];
  confidence: number;
};

export type Prediction = {
  id: string;
  userId: string;
  raceId: string;
  raceDate: string;
  raceName: string;
  venue: string;
  raceType: RaceType;
  horses: PredictionHorse[];
  recommendedBets: RecommendedBet[];
  analysis: string;
  createdAt: string;
};

export type BetRecord = {
  betType: BetType;
  combination: string;
  amount: number;
};

export type RaceResult = {
  id: string;
  predictionId: string;
  userId: string;
  raceDate: string;
  raceName: string;
  venue: string;
  first: number;
  second: number;
  third: number;
  payouts: { betType: BetType; amount: number }[];
  bets: BetRecord[];
  totalBet: number;
  totalReturn: number;
  profit: number;
  createdAt: string;
};

export type PerformanceStats = {
  betType: BetType;
  totalBets: number;
  wins: number;
  hitRate: number;
  totalBetAmount: number;
  totalReturnAmount: number;
  recoveryRate: number;
};
