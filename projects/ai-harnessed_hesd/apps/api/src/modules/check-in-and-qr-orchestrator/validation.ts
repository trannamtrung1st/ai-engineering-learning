import { sessionCheckInGate } from "../session-lifecycle/validation.js";
import type { SessionState } from "../session-lifecycle/types.js";
import type { CheckInOutcome, EffectivePolicy, GpsPayload } from "./types.js";

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
    const gpsFailure = evaluateGpsPolicy(input.gps, input.policy);
    if (gpsFailure) return gpsFailure;
  }

  return null;
}

function evaluateGpsPolicy(
  gps: GpsPayload,
  policy: EffectivePolicy,
): "GpsDisabled" | "OutOfRadius" | "LowAccuracy" | null {
  if (
    !Number.isFinite(gps.latitude) ||
    !Number.isFinite(gps.longitude) ||
    !Number.isFinite(gps.accuracyMeters) ||
    gps.latitude < -90 ||
    gps.latitude > 90 ||
    gps.longitude < -180 ||
    gps.longitude > 180 ||
    gps.accuracyMeters < 0
  ) {
    return "GpsDisabled";
  }

  if (
    policy.gpsMinAccuracyMeters !== null &&
    gps.accuracyMeters > policy.gpsMinAccuracyMeters
  ) {
    return "LowAccuracy";
  }

  if (policy.gpsRadiusMeters !== null) {
    // Radius enforcement requires room coordinates — deferred to repository when room is known.
    return null;
  }

  return null;
}

/** BR-11 / BR-12 — Present vs Late from session open time and policy windows. */
export function resolveAttendanceStatus(
  openedAt: string,
  checkInAt: Date,
  policy: EffectivePolicy,
): "Present" | "Late" {
  const openedMs = new Date(openedAt).getTime();
  const elapsedMinutes = (checkInAt.getTime() - openedMs) / 60_000;
  if (elapsedMinutes <= policy.presentWindowMinutes) {
    return "Present";
  }
  return "Late";
}

export function haversineMeters(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const r = 6_371_000;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}
