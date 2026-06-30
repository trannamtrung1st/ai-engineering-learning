import { useCallback, useEffect, useState } from "react";
import { useLiveCountdown } from "@/hooks/use-live-countdown";
import { useQrTokenPoll } from "@/hooks/use-qr-token-poll";

/** NFR-06 — shared QR poll, countdown sync, and cross-fade refresh cycle */
export function useQrDisplayCycle(sessionId: string | undefined, enabled: boolean) {
  const [tokenKey, setTokenKey] = useState(0);
  const [fading, setFading] = useState(false);
  const qrQuery = useQrTokenPoll(sessionId, enabled);

  const handleCycleComplete = useCallback(() => {
    setFading(true);
    void qrQuery.refetch();
    window.setTimeout(() => {
      setTokenKey((k) => k + 1);
      setFading(false);
    }, 300);
  }, [qrQuery]);

  const { secondsRemaining } = useLiveCountdown({
    onCycleComplete: handleCycleComplete,
    syncSeconds: qrQuery.data?.secondsRemaining,
    active: enabled,
  });

  useEffect(() => {
    if (qrQuery.data?.tokenId) {
      setTokenKey((k) => k + 1);
    }
  }, [qrQuery.data?.tokenId]);

  return {
    qrQuery,
    liveToken: qrQuery.data,
    secondsRemaining,
    tokenKey,
    fading,
  };
}
