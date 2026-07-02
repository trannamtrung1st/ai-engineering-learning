import { DEFAULT_PASSWORD } from "./constants.js";

export type PersonaRole = "student" | "lecturer";

/** Seed-aligned persona for committed UI regression smoke journeys. */
export interface SmokePersona {
  role: PersonaRole;
  email: string;
  password: string;
  displayName: string;
  /** Post-login landing route once auth UI ships (module-identity-and-access). */
  homePath: string;
  viewport: { width: number; height: number };
}

/** Desktop lecturer workspace profile — testing-plan §6.2 Chromium desktop matrix. */
export const LECTURER_PERSONA: SmokePersona = {
  role: "lecturer",
  email: "lecturer@attendly.local",
  password: DEFAULT_PASSWORD,
  displayName: "Nguyễn Văn Giảng",
  homePath: "/lecturer/sessions",
  viewport: { width: 1280, height: 720 },
};

/** Mobile student check-in profile — NFR-14 mobile-first PG-02 flows. */
export const STUDENT_PERSONA: SmokePersona = {
  role: "student",
  email: "student1@attendly.local",
  password: DEFAULT_PASSWORD,
  displayName: "Trần Thị Sinh Viên",
  homePath: "/check-in",
  viewport: { width: 375, height: 667 },
};

/** Deterministic IDs from scripts/db-seed.mjs for cross-layer traceability. */
export const SEED_FIXTURE_IDS = {
  lecturerUser: "60000000-0000-4000-8000-000000000001",
  studentUser: "60000000-0000-4000-8000-000000000002",
  section: "50000000-0000-4000-8000-000000000001",
  scheduledSession: "70000000-0000-4000-8000-000000000001",
  openSession: "70000000-0000-4000-8000-000000000002",
} as const;
