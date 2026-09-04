import { predictDate } from "../src/lib/m7-engine";

const preds = predictDate("2026-08-30");
console.log("Total races:", preds.length);
console.log("Should bet:", preds.filter(p => p.shouldBet).length);
console.log("Skip:", preds.filter(p => !p.shouldBet).length);

for (const p of preds.slice(0, 5)) {
  const label = p.shouldBet ? ">>> BET" : "    SKIP";
  console.log(`${label} | ${p.venueName} R${p.raceNumber} ${p.surface}${p.distance}m ${p.trackCondition ?? ""} | Top3: ${p.combination} PB=${p.predBlend.toFixed(2)} TrioProb=${(p.trioProb*100).toFixed(1)}%`);
  for (const h of p.horses.slice(0, 3)) {
    console.log(`       #${h.horseNumber} IDM=${h.idm} Score=${h.totalScore.toFixed(1)} Blend=${(h.blendedProb*100).toFixed(1)}%`);
  }
}
