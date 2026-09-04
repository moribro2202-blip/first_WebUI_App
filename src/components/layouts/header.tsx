"use client";

import { Trophy, Menu } from "lucide-react";
import { Button } from "@/components/ui/button";

type HeaderProps = {
  onToggleSidebar: () => void;
};

export function Header({ onToggleSidebar }: HeaderProps) {
  return (
    <header className="flex h-14 items-center border-b bg-card px-4">
      <Button
        variant="ghost"
        size="icon"
        className="md:hidden"
        onClick={onToggleSidebar}
        aria-label="メニューを開く"
      >
        <Menu className="h-5 w-5" />
      </Button>
      <div className="flex items-center gap-2 px-2">
        <Trophy className="h-5 w-5 text-primary" />
        <h1 className="text-lg font-bold">競馬AI予想</h1>
      </div>
    </header>
  );
}
