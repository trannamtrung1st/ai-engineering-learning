import { sessionCheckInGate } from "../session-lifecycle/validation.js";
import type { SessionState } from "../session-lifecycle/types.js";
import {
  evaluateGpsPayload,
  haversineMeters,
  resolveAttendanceStatus,
} from "../policy-engine/validation.js";
import type { CheckInOutcome, EffectivePolicy, GpsPayload } from "./types.js";

export { evaluateGpsPayload, haversineMeters, resolveAttendanceStatus };

const RESOLVED_ATTENDANCE_STATUSES = new Set([
  "Present",
  "Late",
  "Manual Present",
  "Excused",
]);

export function isResolvedAttendanceStatus(status: string): boolean {
  return RESOLVED_ATTENDANCE_STATUSES.has(status);
}

/** VR §2.2 — deterministic short-circuit order for check-in domain rules. */
export function evaluateCheckInFailure(input: {
  sessionState: SessionState;
  tokenFound: boolean;
  tokenExpired: boolean;
  enrolled: boolean;
  existingAttendanceStatus: string | null;
  policy: EffectivePolicy;
  gps: GpsPayload | null | undefined;
}): Exclude<CheckInOutcome, "Success"> | null {
  const sessionGate = sessionCheckInGate(input.sessionState);
  if (sessionGate === "SessionNotOpen") return "SessionNotOpen";
  if (sessionGate === "SessionClosed") return "SessionClosed";

  if (!input.tokenFound) return "InvalidQr";
  if (input.tokenExpired) return "ExpiredQr";

  if (!input.enrolled) return "NotEnrolled";

  if (
    input.existingAttendanceStatus &&
    isResolvedAttendanceStatus(input.existingAttendanceStatus)
  ) {
    return "DuplicateCheckIn";
  }

  if (input.policy.gpsRequired) {
    if (!input.gps) return "GpsRequired";
    const gpsFailure = evaluateGpsPayload(input.gps, input.policy);
    if (gpsFailure) return gpsFailure;
  }

  return null;
}
