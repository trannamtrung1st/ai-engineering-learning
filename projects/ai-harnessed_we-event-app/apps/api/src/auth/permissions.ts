import { ApiError } from "../errors/api-error.js";
import type { ActorRole, JwtPayload } from "./types.js";

/**
 * FR-25: Capability grants aligned with docs/technical/01-roles-permissions.md §2.
 */
export type Capability =
  | "event.create"
  | "event.publish"
  | "event.configure"
  | "registration.register"
  | "registration.cancel_own"
  | "checkin.staff"
  | "checkin.self"
  | "feedback.submit"
  | "eligibility.revoke"
  | "audit.read"
  | "export.reports"
  | "dashboard.view";

const ROLE_PERMISSIONS: Record<Capability, readonly ActorRole[]> = {
  "event.create": ["OrganizerAdmin"],
  "event.publish": ["OrganizerAdmin"],
  "event.configure": ["OrganizerAdmin"],
  "registration.register": ["Participant"],
  "registration.cancel_own": ["Participant"],
  "checkin.staff": ["OrganizerAdmin", "OrganizerStaff"],
  "checkin.self": ["Participant"],
  "feedback.submit": ["Participant"],
  "eligibility.revoke": ["OrganizerAdmin"],
  "audit.read": ["OrganizerAdmin"],
  "export.reports": ["OrganizerAdmin"],
  "dashboard.view": ["OrganizerAdmin", "OrganizerStaff"],
};

export function roleHasCapability(role: ActorRole, capability: Capability): boolean {
  return ROLE_PERMISSIONS[capability].includes(role);
}

/**
 * Authorization decision pattern step 2 — validate role permission before scope/domain.
 */
export function assertRolePermission(actor: JwtPayload, capability: Capability): void {
  if (!roleHasCapability(actor.role, capability)) {
    throw new ApiError({
      code: "FORBIDDEN",
      message: "You do not have permission to perform this action.",
      statusCode: 403,
      details: { capability, role: actor.role },
    });
  }
}
