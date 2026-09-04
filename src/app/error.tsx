"use client";

import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 p-4">
      <AlertTriangle className="h-12 w-12 text-destructive" />
      <h2 className="text-xl font-bold">エラーが発生しました</h2>
      <p className="text-center text-muted-foreground">
        {error.message || "予期しないエラーが発生しました"}
      </p>
      <Button onClick={reset}>再試行</Button>
    </div>
  );
}
