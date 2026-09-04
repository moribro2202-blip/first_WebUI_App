"use client";

import { useState, useEffect } from "react";
import { Database, Upload, Loader2, CheckCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

type DbStats = {
  races: number;
  entries: number;
  results: number;
  horses: number;
};

type ImportResultItem = {
  file: string;
  type: string;
  records: number;
  status: "success" | "error";
  error?: string;
};

export function JrdbImportForm() {
  const [stats, setStats] = useState<DbStats | null>(null);
  const [importing, setImporting] = useState(false);
  const [extendedImporting, setExtendedImporting] = useState(false);
  const [importResults, setImportResults] = useState<ImportResultItem[]>([]);
  const [extendedResult, setExtendedResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  const fetchStats = async () => {
    try {
      const res = await fetch("/api/jrdb/import");
      if (res.ok) {
        const data = await res.json();
        setStats(data.stats);
      }
    } catch {
      // DB未作成の場合はスキップ
    }
  };

  const handleImport = async () => {
    setImporting(true);
    setError(null);
    setImportResults([]);

    try {
      const res = await fetch("/api/jrdb/import", { method: "POST" });
      const data = await res.json();

      if (!res.ok) {
        setError(data.error);
        return;
      }

      setImportResults(data.results);
      setStats(data.stats);
    } catch {
      setError("インポートに失敗しました");
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <Button onClick={handleImport} disabled={importing || extendedImporting}>
          {importing ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Upload className="mr-1 h-4 w-4" />
          )}
          {importing ? "インポート中..." : "基本インポート"}
        </Button>
        <Button
          onClick={async () => {
            setExtendedImporting(true);
            setError(null);
            setExtendedResult(null);
            try {
              const res = await fetch("/api/jrdb/import/extended", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({}) });
              const data = await res.json();
              if (!res.ok) { setError(data.error); return; }
              setExtendedResult(`ZIP: ${data.zipExtracted}件解凍 / BAC拡張: ${data.bacUpdated}件 / TYB(IDM): ${data.tybUpdated}件 / DB: ${data.dbStats.races}R ${data.dbStats.withIdm}IDM`);
              fetchStats();
            } catch { setError("拡張インポートに失敗"); }
            finally { setExtendedImporting(false); }
          }}
          disabled={importing || extendedImporting}
          variant="outline"
        >
          {extendedImporting ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Database className="mr-1 h-4 w-4" />
          )}
          {extendedImporting ? "処理中..." : "ZIP解凍+IDM拡張"}
        </Button>
      </div>

      {stats && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="レース" value={stats.races} />
          <StatCard label="出走馬" value={stats.entries} />
          <StatCard label="成績" value={stats.results} />
          <StatCard label="馬マスタ" value={stats.horses} />
        </div>
      )}

      <div className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
        <p className="font-medium">JRDBデータの配置場所</p>
        <p className="mt-1">
          プロジェクトルートの{" "}
          <code className="rounded bg-background px-1 py-0.5 text-xs">data/jrdb/</code>{" "}
          以下にファイルを配置してください。
        </p>
        <div className="mt-2 space-y-0.5 font-mono text-xs">
          <p>data/jrdb/BAC/ ... レース番組データ</p>
          <p>data/jrdb/KYI/ ... 競走馬情報</p>
          <p>data/jrdb/SED/ ... 成績データ</p>
          <p>data/jrdb/UKC/ ... 馬基本データ</p>
        </div>
      </div>

      {extendedResult && (
        <div className="flex items-center gap-2 rounded-md bg-green-50 dark:bg-green-950 p-3 text-sm text-green-700 dark:text-green-300">
          <CheckCircle className="h-4 w-4" />
          {extendedResult}
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="h-4 w-4" />
          {error}
        </div>
      )}

      {importResults.length > 0 && (
        <div className="space-y-1">
          <p className="text-sm font-medium">インポート結果</p>
          <div className="max-h-40 overflow-y-auto rounded-md border p-2 text-xs">
            {importResults.map((r, i) => (
              <div key={i} className="flex items-center gap-2 py-0.5">
                {r.status === "success" ? (
                  <CheckCircle className="h-3 w-3 text-green-500" />
                ) : (
                  <AlertTriangle className="h-3 w-3 text-destructive" />
                )}
                <span className="font-mono">
                  [{r.type}] {r.file}
                </span>
                <span className="text-muted-foreground">
                  {r.status === "success"
                    ? `${r.records}件`
                    : r.error}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border p-3 text-center">
      <div className="flex items-center justify-center gap-1">
        <Database className="h-3 w-3 text-muted-foreground" />
        <p className="text-xs text-muted-foreground">{label}</p>
      </div>
      <p className="text-lg font-bold">{value.toLocaleString()}</p>
    </div>
  );
}
