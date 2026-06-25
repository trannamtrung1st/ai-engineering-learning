export const queryKeys = {
  health: ["health"] as const,
  session: ["session", "me"] as const,
  events: {
    all: ["events"] as const,
    list: (params?: {
      page?: number;
      pageSize?: number;
      q?: string;
      state?: string;
    }) => [...queryKeys.events.all, "list", params ?? {}] as const,
    listRoot: () => [...queryKeys.events.all, "list"] as const,
    detail: (eventId: string) => [...queryKeys.events.all, "detail", eventId] as const,
  },
  registrations: {
    all: ["registrations"] as const,
    status: (eventId: string) =>
      [...queryKeys.registrations.all, "status", eventId] as const,
    mine: (params?: { page?: number; pageSize?: number; state?: string }) =>
      [...queryKeys.registrations.all, "mine", params ?? {}] as const,
    mineAll: () => [...queryKeys.registrations.all, "mine"] as const,
  },
  eligibility: {
    me: (eventId: string) => ["eligibility", "me", eventId] as const,
  },
  organizer: {
    dashboard: (eventId: string) => ["organizer", "dashboard", eventId] as const,
    events: {
      all: ["organizer", "events"] as const,
      list: (params?: {
        page?: number;
        pageSize?: number;
        q?: string;
        state?: string;
      }) => [...queryKeys.organizer.events.all, "list", params ?? {}] as const,
      listRoot: () => [...queryKeys.organizer.events.all, "list"] as const,
      detail: (eventId: string) =>
        [...queryKeys.organizer.events.all, "detail", eventId] as const,
    },
    registrations: (eventId: string, params?: { page?: number; state?: string }) =>
      ["organizer", "registrations", eventId, params ?? {}] as const,
    waitlist: (eventId: string, params?: { page?: number }) =>
      ["organizer", "waitlist", eventId, params ?? {}] as const,
    attendance: (eventId: string, params?: { page?: number }) =>
      ["organizer", "attendance", eventId, params ?? {}] as const,
    eligibility: (
      eventId: string,
      params?: { page?: number; eligibility?: string },
    ) => ["organizer", "eligibility", eventId, params ?? {}] as const,
    audit: (eventId: string, params?: { page?: number }) =>
      ["organizer", "audit", eventId, params ?? {}] as const,
    checkIn: (eventId: string) => ["organizer", "check-in", eventId] as const,
  },
} as const;
