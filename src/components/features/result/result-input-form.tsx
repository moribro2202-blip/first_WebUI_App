"use client";

import { useState } from "react";
import { Save, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { BET_TYPE_LABELS } from "@/types";
import type { BetType, BetRecord, Prediction } from "@/types";
import { saveResult } from "@/lib/storage";
import { calcReturn } from "@/lib/calc-profit";

const betTypes: BetType[] = [
  "tansho", "fukusho", "umaren", "umatan", "wide", "sanrenpuku", "sanrentan",
];

type Props = {
  prediction: Prediction;
  onSaved: () => void;
};

export function ResultInputForm({ prediction, onSaved }: Props) {
  const [first, setFirst] = useState<number>(0);
  const [second, setSecond] = useState<number>(0);
  const [third, setThird] = useState<number>(0);

  const [payouts, setPayouts] = useState<{ betType: BetType; amount: number }[]>(
    betTypes.map((bt) => ({ betType: bt, amount: 0 }))
  );

  const [bets, setBets] = useState<BetRecord[]>([]);

  const addBet = () => {
    setBets([...bets, { betType: "tansho", combination: "", amount: 100 }]);
  };

  const updateBet = (index: number, patch: Partial<BetRecord>) => {
    setBets(bets.map((b, i) => (i === index ? { ...b, ...patch } : b)));
  };

  const removeBet = (index: number) => {
    setBets(bets.filter((_, i) => i !== index));
  };

  const updatePayout = (betType: BetType, amount: number) => {
    setPayouts(payouts.map((p) => (p.betType === betType ? { ...p, amount } : p)));
  };

  const handleSave = () => {
    const order = { first, second, third };
    const activePayout = payouts.filter((p) => p.amount > 0);
    const { totalBet, totalReturn, profit } = calcReturn(bets, order, activePayout);

    saveResult({
      id: crypto.randomUUID(),
      predictionId: prediction.id,
      userId: "local",
      raceDate: prediction.raceDate,
      raceName: prediction.raceName,
      venue: prediction.venue,
      first,
      second,
      third,
      payouts: activePayout,
      bets,
      totalBet,
      totalReturn,
      profit,
      createdAt: new Date().toISOString(),
    });

    onSaved();
  };

  return (
    <div className="space-y-6">
      {/* 着順 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">着順</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4">
            <div className="space-y-2">
              <Label>1着 馬番</Label>
              <Input
                type="number"
                value={first || ""}
                onChange={(e) => setFirst(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label>2着 馬番</Label>
              <Input
                type="number"
                value={second || ""}
                onChange={(e) => setSecond(Number(e.target.value))}
              />
            </div>
            <div className="space-y-2">
              <Label>3着 馬番</Label>
              <Input
                type="number"
                value={third || ""}
                onChange={(e) => setThird(Number(e.target.value))}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 配当 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">配当（100円あたり）</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {payouts.map((p) => (
              <div key={p.betType} className="space-y-1">
                <Label className="text-xs">{BET_TYPE_LABELS[p.betType]}</Label>
                <Input
                  type="number"
                  value={p.amount || ""}
                  onChange={(e) => updatePayout(p.betType, Number(e.target.value))}
                  placeholder="0"
                  className="h-8 text-sm"
                />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* 購入馬券 */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">購入馬券</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {bets.map((bet, i) => (
            <div key={i} className="flex items-end gap-2">
              <div className="w-28 space-y-1">
                <Label className="text-xs">券種</Label>
                <Select
                  value={bet.betType}
                  onValueChange={(v) => updateBet(i, { betType: v as BetType })}
                >
                  <SelectTrigger className="h-8 text-sm">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {betTypes.map((bt) => (
                      <SelectItem key={bt} value={bt}>
                        {BET_TYPE_LABELS[bt]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex-1 space-y-1">
                <Label className="text-xs">買い目</Label>
                <Input
                  value={bet.combination}
                  onChange={(e) => updateBet(i, { combination: e.target.value })}
                  placeholder="例: 3-5"
                  className="h-8 text-sm"
                />
              </div>
              <div className="w-24 space-y-1">
                <Label className="text-xs">金額</Label>
                <Input
                  type="number"
                  value={bet.amount || ""}
                  onChange={(e) => updateBet(i, { amount: Number(e.target.value) })}
                  className="h-8 text-sm"
                />
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-destructive"
                onClick={() => removeBet(i)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addBet}>
            <Plus className="mr-2 h-4 w-4" />
            馬券を追加
          </Button>
        </CardContent>
      </Card>

      <Button
        onClick={handleSave}
        disabled={!first || !second || !third}
        className="w-full"
        size="lg"
      >
        <Save className="mr-2 h-5 w-5" />
        結果を保存
      </Button>
    </div>
  );
}
