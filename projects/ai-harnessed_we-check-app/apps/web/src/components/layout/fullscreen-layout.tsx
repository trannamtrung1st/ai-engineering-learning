import { SessionStatus } from "@wecheck/domain";
import { Outlet } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { QrCountdown } from "@/components/ui/qr-countdown";
import { StatusBadge } from "@/components/ui/status-badge";
import { appCopy } from "@/lib/copy/status-labels";

export interface FullscreenLayoutProps {
  sessionTitle?: string;
  roomName?: string;
  secondsRemaining?: number;
  onExit?: () => void;
}

export function FullscreenLayout({
  sessionTitle = "Buổi học",
  roomName = "Phòng học",
  secondsRemaining = 30,
  onExit,
}: FullscreenLayoutProps) {
  return (
    <div
      className="flex min-h-screen flex-col bg-qr-bg text-text-inverse"
      data-testid="fullscreen-layout"
    >
      <header className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
        <div>
          <p className="text-h2 font-semibold">{sessionTitle}</p>
          <p className="text-body text-text-inverse/80">{roomName}</p>
        </div>
        <StatusBadge status={SessionStatus.Active} />
      </header>
      <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6">
        <div
          className="flex aspect-square w-[var(--size-qr-projector)] max-w-full items-center justify-center rounded-lg bg-qr-fg/10"
          aria-hidden="true"
          data-testid="qr-placeholder"
        />
        <QrCountdown secondsRemaining={secondsRemaining} presentation />
      </main>
      <footer className="flex items-center justify-between px-6 py-4">
        <Button variant="ghost" className="text-text-inverse hover:bg-white/10" onClick={onExit}>
          {appCopy.exitFullscreen}
        </Button>
        <Outlet />
      </footer>
    </div>
  );
}
