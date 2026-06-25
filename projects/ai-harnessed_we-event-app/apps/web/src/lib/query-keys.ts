export const queryKeys = {
  health: ["health"] as const,
  session: ["session", "me"] as const,
  events: {
    all: ["events"] as const,
    list: () => [...queryKeys.events.all, "list"] as const,
    detail: (eventId: string) => [...queryKeys.events.all, "detail", eventId] as const,
  },
  registrations: {
    all: ["registrations"] as const,
    status: (eventId: string) =>
      [...queryKeys.registrations.all, "status", eventId] as const,
    mine: () => [...queryKeys.registrations.all, "mine"] as const,
  },
  eligibility: {
    me: (eventId: string) => ["eligibility", "me", eventId] as const,
  },
  organizer: {
    dashboard: () => ["organizer", "dashboard"] as const,
    checkIn: (eventId: string) => ["organizer", "check-in", eventId] as const,
  },
} as const;
