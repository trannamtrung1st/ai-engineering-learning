import { useQuery } from "@tanstack/react-query";
import { fetchQrCurrent } from "@/lib/check-in-api";

/** NFR-06 — poll instructor QR token from API for rotation-aware display */
export function useQrTokenPoll(sessionId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["qr-token", sessionId],
    queryFn: () => fetchQrCurrent(sessionId!),
    enabled: Boolean(sessionId) && enabled,
    refetchInterval: 5_000,
    retry: false,
  });
}
