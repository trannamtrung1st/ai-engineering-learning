export const queryKeys = {
  health: ["health"] as const,
  events: {
    all: ["events"] as const,
    list: () => [...queryKeys.events.all, "list"] as const,
    detail: (eventId: string) => [...queryKeys.events.all, "detail", eventId] as const,
  },
  organizer: {
    dashboard: () => ["organizer", "dashboard"] as const,
    checkIn: (eventId: string) => ["organizer", "check-in", eventId] as const,
  },
} as const;
