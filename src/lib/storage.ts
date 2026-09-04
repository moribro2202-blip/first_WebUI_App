import type { Prediction, RaceResult } from "@/types";

const PREDICTIONS_KEY = "keiba-predictions";
const RESULTS_KEY = "keiba-results";

function getItem<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  const raw = localStorage.getItem(key);
  return raw ? (JSON.parse(raw) as T[]) : [];
}

function setItem<T>(key: string, data: T[]) {
  localStorage.setItem(key, JSON.stringify(data));
}

// Predictions
export function getPredictions(): Prediction[] {
  return getItem<Prediction>(PREDICTIONS_KEY);
}

export function savePrediction(prediction: Prediction) {
  const list = getPredictions();
  list.unshift(prediction);
  setItem(PREDICTIONS_KEY, list);
}

export function getPredictionById(id: string): Prediction | undefined {
  return getPredictions().find((p) => p.id === id);
}

// Results
export function getResults(): RaceResult[] {
  return getItem<RaceResult>(RESULTS_KEY);
}

export function saveResult(result: RaceResult) {
  const list = getResults();
  list.unshift(result);
  setItem(RESULTS_KEY, list);
}

export function getResultByPredictionId(predictionId: string): RaceResult | undefined {
  return getResults().find((r) => r.predictionId === predictionId);
}
