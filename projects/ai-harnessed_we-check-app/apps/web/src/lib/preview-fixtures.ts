/** Preview fixture IDs — must match apps/api/src/infra/preview-seed.ts PREVIEW_IDS */
export const PREVIEW_SESSION_IDS = {
  active: "30000000-0000-4000-8000-000000000301",
  draft: "30000000-0000-4000-8000-000000000302",
  closed: "30000000-0000-4000-8000-000000000303",
} as const;

export const PREVIEW_TOKEN_IDS = {
  stale: "40000000-0000-4000-8000-000000000401",
  consumed: "40000000-0000-4000-8000-000000000402",
  valid: "40000000-0000-4000-8000-000000000403",
  closedStale: "40000000-0000-4000-8000-000000000404",
} as const;

/** Room GPS for preview session — must match apps/api/src/infra/preview-seed.ts */
export const PREVIEW_ROOM_GPS = {
  latitude: 10.762622,
  longitude: 106.660172,
} as const;

const PREVIEW_HARNESS_TOKEN_IDS = new Set<string>(Object.values(PREVIEW_TOKEN_IDS));

export function isPreviewHarnessTokenId(tokenId: string | null | undefined): boolean {
  if (!tokenId) return false;
  return PREVIEW_HARNESS_TOKEN_IDS.has(tokenId);
}

/** Shell route aliases mapped to seeded Postgres IDs (browser gate fixtures). */
export const PREVIEW_ALIASES: Record<string, string> = {
  "sess-1": PREVIEW_SESSION_IDS.active,
  "sess-2": PREVIEW_SESSION_IDS.draft,
  "sess-3": PREVIEW_SESSION_IDS.closed,
  "stale-token-id": PREVIEW_TOKEN_IDS.stale,
  "consumed-token-id": PREVIEW_TOKEN_IDS.consumed,
  "valid-token-id": PREVIEW_TOKEN_IDS.valid,
  "closed-stale-token-id": PREVIEW_TOKEN_IDS.closedStale,
};

export const PREVIEW_CREDENTIALS = {
  student: { email: "student@example.edu.vn", password: "StudentPass8" },
  instructor: { email: "instructor@example.edu.vn", password: "InstructorPass8" },
  admin: { email: "admin@example.edu.vn", password: "AdminPass123" },
  deactivated: { email: "deactivated@example.edu.vn", password: "StudentPass8" },
  studentB: { email: "studentb@example.edu.vn", password: "StudentPass8" },
  studentC: { email: "studentc@example.edu.vn", password: "StudentPass8" },
  instructor2: { email: "instructor2@example.edu.vn", password: "InstructorPass8" },
} as const;

export function resolvePreviewId(aliasOrId: string | null | undefined): string | null {
  if (!aliasOrId) return null;
  return PREVIEW_ALIASES[aliasOrId] ?? aliasOrId;
}

export { loginReturnUrl } from "@/lib/auth-redirect";
