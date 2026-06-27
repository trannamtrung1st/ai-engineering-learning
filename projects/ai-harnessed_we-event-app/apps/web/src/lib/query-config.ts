/**
 * Live refresh intervals per docs/ui-ux/02-ui-framework-tech-stack.md
 * — event list, organizer dashboard, and check-in console polling policies.
 */
export const LIVE_REFRESH_INTERVALS = {
  /** Periodic refresh during open registration windows */
  eventList: 60_000,
  /** Shorter interval while organizer operations are active */
  organizerDashboard: 5_000,
  /** Polling while check-in console is open */
  checkInConsole: 3_000,
} as const;

export type LiveRefreshMode = keyof typeof LIVE_REFRESH_INTERVALS;

/** NFR-06 — shared TanStack Query polling policy for live organizer surfaces. */
export function getLiveQueryPolicy(mode: LiveRefreshMode) {
  const refetchInterval = LIVE_REFRESH_INTERVALS[mode];

  return {
    refetchInterval,
    refetchIntervalInBackground: mode !== "checkInConsole",
    refetchOnWindowFocus: true,
    staleTime: Math.floor(refetchInterval / 2),
    // Surface background poll failures immediately (TC-NFR-06-012); global retry would mask transient 503s.
    retry: mode === "organizerDashboard" ? false : undefined,
  } as const;
}
