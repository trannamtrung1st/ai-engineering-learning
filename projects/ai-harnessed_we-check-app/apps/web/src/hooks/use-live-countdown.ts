import { useCallback, useEffect, useState } from "react";

const QR_CYCLE_SECONDS = 30;

export interface UseLiveCountdownOptions {
  /** Initial seconds remaining (default 30). */
  initialSeconds?: number;
  /** Called when countdown reaches 0 before reset. */
  onCycleComplete?: () => void;
  /** Whether the timer is active (default true). */
  active?: boolean;
  /** Sync countdown from API poll (NFR-06). */
  syncSeconds?: number;
}

/** NFR-06 — client-side countdown that decrements every second and resets at 0. */
export function useLiveCountdown({
  initialSeconds = QR_CYCLE_SECONDS,
  onCycleComplete,
  active = true,
  syncSeconds,
}: UseLiveCountdownOptions = {}) {
  const [secondsRemaining, setSecondsRemaining] = useState(
    syncSeconds ?? initialSeconds,
  );

  const reset = useCallback(() => {
    setSecondsRemaining(QR_CYCLE_SECONDS);
  }, []);

  useEffect(() => {
    if (syncSeconds !== undefined) {
      setSecondsRemaining(syncSeconds);
    }
  }, [syncSeconds]);

  useEffect(() => {
    if (!active) return;

    const id = window.setInterval(() => {
      setSecondsRemaining((prev) => {
        if (prev <= 1) {
          onCycleComplete?.();
          return QR_CYCLE_SECONDS;
        }
        return prev - 1;
      });
    }, 1000);

    return () => window.clearInterval(id);
  }, [active, onCycleComplete]);

  return { secondsRemaining, reset };
}

export { QR_CYCLE_SECONDS };
