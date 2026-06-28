import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { SessionStatus } from "@wecheck/domain";
import { Button } from "@/components/ui/button";
import { QrCountdown } from "@/components/ui/qr-countdown";
import { StatusBadge } from "@/components/ui/status-badge";
import { useLiveCountdown } from "@/hooks/use-live-countdown";
import { useQrTokenPoll } from "@/hooks/use-qr-token-poll";
import { resolvePreviewId } from "@/lib/preview-fixtures";
import { appCopy } from "@/lib/copy/status-labels";

/** NFR-06 / NFR-20 — fullscreen QR presentation with live countdown and rotation */
export function QrPresentPage() {
  const { id: routeId } = useParams<{ id: string }>();
  const id = resolvePreviewId(routeId) ?? routeId;
  const navigate = useNavigate();
  const [tokenKey, setTokenKey] = useState(0);
  const [sessionEnded, setSessionEnded] = useState(false);
  const [fading, setFading] = useState(false);

  const qrQuery = useQrTokenPoll(id, !sessionEnded);
  const liveToken = qrQuery.data;

  const handleExit = useCallback(() => {
    if (id) {
      navigate(`/sessions/${id}?tab=qr`);
      return;
    }
    navigate(-1);
  }, [id, navigate]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        handleExit();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [handleExit]);

  const handleCycleComplete = useCallback(() => {
    setFading(true);
    window.setTimeout(() => {
      setTokenKey((k) => k + 1);
      setFading(false);
    }, 300);
  }, []);

  useEffect(() => {
    if (liveToken?.tokenId) {
      setTokenKey((k) => k + 1);
    }
  }, [liveToken?.tokenId]);

  const { secondsRemaining } = useLiveCountdown({
    onCycleComplete: handleCycleComplete,
    syncSeconds: liveToken?.secondsRemaining,
    active: !sessionEnded,
  });

  return (
    <div
      className="flex min-h-screen flex-col bg-qr-bg text-text-inverse"
      data-testid="qr-present-page"
    >
      <header className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
        <div>
          <p className="text-h2 font-semibold">Buổi học {id ?? "demo"}</p>
          <p className="text-body text-text-inverse/80">Phòng A101</p>
        </div>
        <StatusBadge status={sessionEnded ? SessionStatus.Closed : SessionStatus.Active} />
      </header>

      <main className="relative flex flex-1 flex-col items-center justify-center gap-8 px-6">
        <div
          key={tokenKey}
          data-testid="qr-code-image"
          data-token-id={liveToken?.tokenId}
          className={`flex aspect-square w-[var(--size-qr-projector)] max-w-full items-center justify-center rounded-lg bg-qr-fg/10 transition-opacity duration-300 ${fading ? "opacity-0" : "opacity-100"}`}
          aria-label="Mã QR điểm danh buổi học"
        >
          <div className="grid grid-cols-12 gap-0.5 p-6">
            {Array.from({ length: 144 }, (_, i) => (
              <div
                key={i}
                className={`h-2 w-2 ${(i + tokenKey) % 4 === 0 ? "bg-qr-fg" : "bg-transparent"}`}
              />
            ))}
          </div>
        </div>
        <QrCountdown secondsRemaining={secondsRemaining} presentation />

        {sessionEnded ? (
          <div
            className="absolute inset-0 flex items-center justify-center bg-black/70"
            data-testid="session-ended-overlay"
          >
            <p className="text-display font-semibold text-text-inverse">Buổi học đã kết thúc</p>
          </div>
        ) : null}
      </main>

      <footer className="relative z-10 flex items-center justify-between px-6 py-4">
        <Button
          type="button"
          variant="ghost"
          className="text-text-inverse hover:bg-white/10"
          onClick={handleExit}
        >
          {appCopy.exitFullscreen}
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="text-text-inverse hover:bg-white/10"
          onClick={() => setSessionEnded(true)}
        >
          Kết thúc buổi học
        </Button>
      </footer>
    </div>
  );
}
