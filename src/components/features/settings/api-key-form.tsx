"use client";

import { useState, useEffect } from "react";
import { Eye, EyeOff, Save, Trash2, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const STORAGE_KEY = "anthropic-api-key";

export function ApiKeyForm() {
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saved, setSaved] = useState(false);
  const [hasSavedKey, setHasSavedKey] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      setApiKey(stored);
      setHasSavedKey(true);
    }
  }, []);

  const handleSave = () => {
    if (!apiKey.trim()) return;
    localStorage.setItem(STORAGE_KEY, apiKey.trim());
    setHasSavedKey(true);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleDelete = () => {
    localStorage.removeItem(STORAGE_KEY);
    setApiKey("");
    setHasSavedKey(false);
    setSaved(false);
  };

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="api-key">Claude API キー</Label>
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Input
              id="api-key"
              type={showKey ? "text" : "password"}
              value={apiKey}
              onChange={(e) => {
                setApiKey(e.target.value);
                setSaved(false);
              }}
              placeholder="sk-ant-..."
              className="pr-10"
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="absolute right-0 top-0 h-full"
              onClick={() => setShowKey(!showKey)}
              aria-label={showKey ? "キーを隠す" : "キーを表示"}
            >
              {showKey ? (
                <EyeOff className="h-4 w-4" />
              ) : (
                <Eye className="h-4 w-4" />
              )}
            </Button>
          </div>
          <Button onClick={handleSave} disabled={!apiKey.trim()}>
            {saved ? (
              <CheckCircle className="mr-1 h-4 w-4" />
            ) : (
              <Save className="mr-1 h-4 w-4" />
            )}
            {saved ? "保存済み" : "保存"}
          </Button>
          {hasSavedKey && (
            <Button variant="destructive" size="icon" onClick={handleDelete} aria-label="キーを削除">
              <Trash2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </div>

      <div className="rounded-md bg-muted p-3 text-sm text-muted-foreground">
        <p className="font-medium">環境変数での設定も可能です</p>
        <p className="mt-1">
          <code className="rounded bg-background px-1 py-0.5 text-xs">
            .env.local
          </code>{" "}
          に{" "}
          <code className="rounded bg-background px-1 py-0.5 text-xs">
            ANTHROPIC_API_KEY=sk-ant-...
          </code>{" "}
          を設定すると、UIでの入力は不要です。
        </p>
        <p className="mt-1">
          UIで保存したキーが優先されます。
        </p>
      </div>
    </div>
  );
}
