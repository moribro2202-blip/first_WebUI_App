"use client";

import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { Sun, Moon, Monitor } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const themes = [
  { value: "light", label: "ライト", icon: Sun },
  { value: "dark", label: "ダーク", icon: Moon },
  { value: "system", label: "システム", icon: Monitor },
] as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    return (
      <div className="flex gap-2">
        {themes.map((t) => (
          <div key={t.value} className="h-10 w-24 rounded-md bg-muted" />
        ))}
      </div>
    );
  }

  return (
    <div className="flex gap-2">
      {themes.map((t) => (
        <Button
          key={t.value}
          variant={theme === t.value ? "default" : "outline"}
          size="sm"
          onClick={() => setTheme(t.value)}
          className={cn("flex items-center gap-2")}
        >
          <t.icon className="h-4 w-4" />
          {t.label}
        </Button>
      ))}
    </div>
  );
}
