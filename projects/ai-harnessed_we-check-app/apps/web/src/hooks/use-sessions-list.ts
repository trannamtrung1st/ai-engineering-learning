import { useQuery } from "@tanstack/react-query";
import { fetchSessions } from "@/lib/sessions-api";

/** FR-04 / AC-04 — instructor session list from API */
export function useSessionsList() {
  return useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 30_000,
  });
}
