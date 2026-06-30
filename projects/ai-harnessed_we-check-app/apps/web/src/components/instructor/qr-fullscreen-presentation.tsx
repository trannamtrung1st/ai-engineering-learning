import { useCallback, useEffect } from "react";
import { SessionStatus } from "@wecheck/domain";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { QrCodeImage } from "@/components/ui/qr-code-image";
import { QrCountdown } from "@/components/ui/qr-countdown";
import { StatusBadge } from "@/components/ui/status-badge";
import { useBelowProjectionSpec } from "@/hooks/use-below-projection-spec";
import { useQrDisplayCycle } from "@/hooks/use-qr-display-cycle";
import { useSessionDetail } from "@/hooks/use-session-detail";
import { appCopy } from "@/lib/copy/status-labels";

export interface QrFullscreenPresentationProps {
  sessionId: string;
  onExit: () => void;
}

/** NFR-06 / NFR-20 — fullscreen classroom QR projection with 30 s rotation */
export function QrFullscreenPresentation({
  sessionId,
  onExit,
}: QrFullscreenPresentationProps) {
  const belowProjectionSpec = useBelowProjectionSpec();
  const sessionQuery = useSessionDetail(sessionId, { refetchIntervalMs: 3_000 });
  const session = sessionQuery.data;
  const sessionStatus = session?.status ?? SessionStatus.Active;
  const isActive = sessionStatus === SessionStatus.Active;

  const { liveToken, secondsRemaining, tokenKey, fading } = useQrDisplayCycle(
    sessionId,
    isActive,
  );

  const handleExit = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    }
    onExit();
  }, [onExit]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        handleExit();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleExit]);

  useEffect(() => {
    const root = document.documentElement;
    if (root.requestFullscreen && !document.fullscreenElement) {
      void root.requestFullscreen().catch(() => {
        /* Fullscreen API optional — layout still covers viewport */
      });
    }
    return () => {
      if (document.fullscreenElement) {
        void document.exitFullscreen().catch(() => undefined);
      }
    };
  }, []);

  const sessionEnded = !isActive;
  const metaLine = session
    ? `${session.classCode} · ${session.subjectCode}`
    : undefined;

  return (
    <div
      className="flex min-h-screen flex-col bg-qr-bg text-text-inverse"
      data-testid="qr-present-page"
    >
      <header className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
        <div>
          <p className="text-h2 font-semibold">
            {session?.title ?? `Buổi học ${sessionId}`}
          </p>
          <p className="text-body text-text-inverse/80">
            {session?.roomName ?? metaLine ?? "Phòng học"}
          </p>
        </div>
        <StatusBadge
          status={sessionEnded ? SessionStatus.Closed : SessionStatus.Active}
        />
      </header>

      {belowProjectionSpec ? (
        <div className="px-6 pt-4" data-testid="projection-resolution-warning">
          <Alert variant="warning" title="Độ phân giải thấp">
            {appCopy.projectionResolutionWarning}
          </Alert>
        </div>
      ) : null}

      <main className="relative flex flex-1 flex-col items-center justify-center gap-8 px-6">
        {isActive ? (
          <>
            <QrCodeImage
              value={liveToken?.qrPayload}
              variant="fullscreen"
              fading={fading}
              imageKey={tokenKey}
              tokenId={liveToken?.tokenId}
              className="max-w-[var(--size-qr-projector)]"
            />
            <QrCountdown secondsRemaining={secondsRemaining} presentation />
            <p className="text-body text-text-inverse/80">Quét mã để điểm danh</p>
          </>
        ) : (
          <div className="text-center" data-testid="session-not-active">
            <p className="text-h2 font-semibold">Buổi học chưa mở hoặc đã kết thúc</p>
          </div>
        )}

        {sessionEnded ? (
          <div
            className="absolute inset-0 flex items-center justify-center bg-black/70"
            data-testid="session-ended-overlay"
          >
            <p className="text-display font-semibold text-text-inverse">
              Buổi học đã kết thúc
            </p>
          </div>
        ) : null}
      </main>

      <footer className="relative z-10 flex items-center px-6 py-4">
        <Button
          type="button"
          variant="ghost"
          className="text-text-inverse hover:bg-white/10"
          onClick={handleExit}
          data-testid="qr-exit-fullscreen"
        >
          {appCopy.exitFullscreen}
        </Button>
      </footer>
    </div>
  );
}
