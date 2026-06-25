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
