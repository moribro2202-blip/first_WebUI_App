"use client";

import { Settings } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { ApiKeyForm } from "@/components/features/settings/api-key-form";
import { ThemeToggle } from "@/components/features/settings/theme-toggle";
import { JrdbImportForm } from "@/components/features/settings/jrdb-import-form";

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Settings className="h-6 w-6" />
        <h2 className="text-2xl font-bold">設定</h2>
      </div>

      <div className="space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>API設定</CardTitle>
            <CardDescription>
              AI予想に使用するClaude APIキーを設定します
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ApiKeyForm />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>JRDBデータ</CardTitle>
            <CardDescription>
              JRDBから取得した競馬データをインポート・管理します
            </CardDescription>
          </CardHeader>
          <CardContent>
            <JrdbImportForm />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>テーマ</CardTitle>
            <CardDescription>
              アプリの外観を変更します
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ThemeToggle />
          </CardContent>
        </Card>
      </div>

      <Separator />

      <div className="text-sm text-muted-foreground">
        <p>競馬AI予想 v0.1.0</p>
      </div>
    </div>
  );
}
