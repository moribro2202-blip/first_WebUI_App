"use client";

import { useState, useEffect } from "react";
import { History, ChevronRight, CheckCircle, XCircle, ClipboardEdit } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { getPredictions, getResultByPredictionId } from "@/lib/storage";
import { ResultInputForm } from "@/components/features/result/result-input-form";
import { PredictionResult } from "@/components/features/predict/prediction-result";
import type { Prediction, RaceResult } from "@/types";

export default function HistoryPage() {
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [results, setResults] = useState<Map<string, RaceResult>>(new Map());
  const [selectedPrediction, setSelectedPrediction] = useState<Prediction | null>(null);
  const [showResultForm, setShowResultForm] = useState(false);
  const [showDetail, setShowDetail] = useState(false);

  const loadData = () => {
    const preds = getPredictions();
    setPredictions(preds);
    const map = new Map<string, RaceResult>();
    for (const p of preds) {
      const r = getResultByPredictionId(p.id);
      if (r) map.set(p.id, r);
    }
    setResults(map);
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleResultSaved = () => {
    setShowResultForm(false);
    setSelectedPrediction(null);
    loadData();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <History className="h-6 w-6" />
        <h2 className="text-2xl font-bold">予想履歴</h2>
      </div>

      {predictions.length === 0 ? (
        <p className="text-muted-foreground">まだ予想がありません</p>
      ) : (
        <div className="space-y-3">
          {predictions.map((pred) => {
            const result = results.get(pred.id);
            return (
              <Card key={pred.id} className="cursor-pointer transition-colors hover:bg-accent/50">
                <CardContent className="flex items-center justify-between py-4">
                  <div
                    className="flex-1"
                    onClick={() => {
                      setSelectedPrediction(pred);
                      setShowDetail(true);
                    }}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-muted-foreground">{pred.raceDate}</span>
                      <span className="font-semibold">{pred.raceName}</span>
                    </div>
                    {result && (
                      <div className="mt-1 flex items-center gap-3 text-sm">
                        <span>着順: {result.first}-{result.second}-{result.third}</span>
                        <span className={result.profit >= 0 ? "text-green-600" : "text-destructive"}>
                          {result.profit >= 0 ? "+" : ""}{result.profit.toLocaleString()}円
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {result ? (
                      <Badge variant={result.profit >= 0 ? "default" : "secondary"}>
                        {result.profit >= 0 ? (
                          <><CheckCircle className="mr-1 h-3 w-3" />的中</>
                        ) : (
                          <><XCircle className="mr-1 h-3 w-3" />不的中</>
                        )}
                      </Badge>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSelectedPrediction(pred);
                          setShowResultForm(true);
                        }}
                      >
                        <ClipboardEdit className="mr-1 h-3 w-3" />
                        結果入力
                      </Button>
                    )}
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* 予想詳細ダイアログ */}
      <Dialog open={showDetail} onOpenChange={setShowDetail}>
        <DialogContent className="max-h-[80vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{selectedPrediction?.raceName}</DialogTitle>
          </DialogHeader>
          {selectedPrediction && (
            <PredictionResult
              horses={selectedPrediction.horses}
              recommendedBets={selectedPrediction.recommendedBets}
              analysis={selectedPrediction.analysis}
            />
          )}
        </DialogContent>
      </Dialog>

      {/* 結果入力ダイアログ */}
      <Dialog open={showResultForm} onOpenChange={setShowResultForm}>
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>結果入力 - {selectedPrediction?.raceName}</DialogTitle>
          </DialogHeader>
          {selectedPrediction && (
            <ResultInputForm
              prediction={selectedPrediction}
              onSaved={handleResultSaved}
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
