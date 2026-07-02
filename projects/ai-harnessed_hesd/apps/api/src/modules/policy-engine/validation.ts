import { ErrorCode } from "@attendly/domain";
import type {
  EffectivePolicyValues,
  FieldOverrides,
  GpsPayload,
  PolicyCreateInput,
  PolicyFieldKey,
  PolicyScopeType,
} from "./types.js";
import { POLICY_FIELD_KEYS, POLICY_SCOPE_TYPES } from "./types.js";

export type PolicyValidationError = { code: typeof ErrorCode.InvalidPayload; message?: string };

export type GpsValidationOutcome = "GpsRequired" | "GpsDisabled" | "OutOfRadius" | "LowAccuracy" | null;

export function isPolicyScopeType(value: string): value is PolicyScopeType {
  return (POLICY_SCOPE_TYPES as readonly string[]).includes(value);
}

export function buildFieldOverridesFromBody(
  body: Record<string, unknown>,
  keys: readonly PolicyFieldKey[] = POLICY_FIELD_KEYS,
): FieldOverrides {
  const overrides: FieldOverrides = {};
  for (const key of keys) {
    if (body[key] !== undefined) {
      overrides[key] = true;
    }
  }
  return overrides;
}

export function mergeFieldOverrides(
  existing: FieldOverrides,
  patch: FieldOverrides,
): FieldOverrides {
  return { ...existing, ...patch };
}

function windowsAreValid(presentWindowMinutes: number, lateWindowMinutes: number): boolean {
  return presentWindowMinutes > 0 && lateWindowMinutes >= 0;
}

export function validatePolicyWindows(
  presentWindowMinutes: number,
  lateWindowMinutes: number,
): PolicyValidationError | null {
  if (!windowsAreValid(presentWindowMinutes, lateWindowMinutes)) {
    return { code: ErrorCode.InvalidPayload, message: "presentWindowMinutes must be > 0" };
  }
  return null;
}

export function validateAbsenceThreshold(
  absenceThresholdPercent: number | null | undefined,
): PolicyValidationError | null {
  if (absenceThresholdPercent === null || absenceThresholdPercent === undefined) {
    return null;
  }
  if (absenceThresholdPercent < 0 || absenceThresholdPercent > 100) {
    return { code: ErrorCode.InvalidPayload, message: "absenceThresholdPercent must be 0–100" };
  }
  return null;
}

export function validateGpsFields(
  gpsRequired: boolean,
  gpsRadiusMeters: number | null | undefined,
  gpsMinAccuracyMeters: number | null | undefined,
): PolicyValidationError | null {
  if (gpsRequired) {
    if (gpsRadiusMeters === null || gpsRadiusMeters === undefined || gpsRadiusMeters <= 0) {
      return { code: ErrorCode.InvalidPayload, message: "gpsRadiusMeters required when gpsRequired" };
    }
  } else if (gpsRadiusMeters !== null && gpsRadiusMeters !== undefined) {
    return { code: ErrorCode.InvalidPayload, message: "gpsRadiusMeters only allowed when gpsRequired" };
  }

  if (gpsMinAccuracyMeters !== null && gpsMinAccuracyMeters !== undefined && gpsMinAccuracyMeters <= 0) {
    return { code: ErrorCode.InvalidPayload, message: "gpsMinAccuracyMeters must be > 0" };
  }

  return null;
}

export function validatePolicyCreateInput(body: Record<string, unknown>): PolicyValidationError | null {
  if (typeof body.scopeType !== "string" || !isPolicyScopeType(body.scopeType)) {
    return { code: ErrorCode.InvalidPayload };
  }

  if (body.scopeType !== "Institution") {
    if (typeof body.scopeId !== "string" || body.scopeId.length === 0) {
      return { code: ErrorCode.InvalidPayload };
    }
  } else if (body.scopeId !== null && body.scopeId !== undefined) {
    return { code: ErrorCode.InvalidPayload };
  }

  const present = Number(body.presentWindowMinutes);
  const late = Number(body.lateWindowMinutes);
  const manualEdit = Number(body.manualEditWindowHours);

  if (!Number.isFinite(present) || !Number.isFinite(late) || !Number.isFinite(manualEdit)) {
    return { code: ErrorCode.InvalidPayload };
  }

  const windowError = validatePolicyWindows(present, late);
  if (windowError) return windowError;

  const thresholdError = validateAbsenceThreshold(
    body.absenceThresholdPercent === null || body.absenceThresholdPercent === undefined
      ? null
      : Number(body.absenceThresholdPercent),
  );
  if (thresholdError) return thresholdError;

  const gpsRequired = body.gpsRequired === true;
  const gpsRadius =
    body.gpsRadiusMeters === null || body.gpsRadiusMeters === undefined
      ? null
      : Number(body.gpsRadiusMeters);
  const gpsAccuracy =
    body.gpsMinAccuracyMeters === null || body.gpsMinAccuracyMeters === undefined
      ? null
      : Number(body.gpsMinAccuracyMeters);

  const gpsError = validateGpsFields(gpsRequired, gpsRadius, gpsAccuracy);
  if (gpsError) return gpsError;

  if (manualEdit < 0) {
    return { code: ErrorCode.InvalidPayload };
  }

  return null;
}

export function validatePolicyUpdateInput(
  body: Record<string, unknown>,
  current: EffectivePolicyValues & { gpsRequired: boolean },
): PolicyValidationError | null {
  const present =
    body.presentWindowMinutes !== undefined ? Number(body.presentWindowMinutes) : current.presentWindowMinutes;
  const late =
    body.lateWindowMinutes !== undefined ? Number(body.lateWindowMinutes) : current.lateWindowMinutes;

  const windowError = validatePolicyWindows(present, late);
  if (windowError) return windowError;

  if (body.absenceThresholdPercent !== undefined) {
    const thresholdError = validateAbsenceThreshold(Number(body.absenceThresholdPercent));
    if (thresholdError) return thresholdError;
  }

  const gpsRequired = body.gpsRequired !== undefined ? body.gpsRequired === true : current.gpsRequired;
  const gpsRadius =
    body.gpsRadiusMeters !== undefined
      ? body.gpsRadiusMeters === null
        ? null
        : Number(body.gpsRadiusMeters)
      : current.gpsRadiusMeters;
  const gpsAccuracy =
    body.gpsMinAccuracyMeters !== undefined
      ? body.gpsMinAccuracyMeters === null
        ? null
        : Number(body.gpsMinAccuracyMeters)
      : current.gpsMinAccuracyMeters;

  const gpsError = validateGpsFields(gpsRequired, gpsRadius, gpsAccuracy);
  if (gpsError) return gpsError;

  return null;
}

export function mapCreateBodyToInput(body: Record<string, unknown>): PolicyCreateInput {
  const fieldOverrides = buildFieldOverridesFromBody(body);
  const gpsRequired = body.gpsRequired === true;

  return {
    scopeType: body.scopeType as PolicyScopeType,
    scopeId: body.scopeType === "Institution" ? null : (body.scopeId as string),
    checkInOpeningOffsetMinutes:
      body.checkInOpeningOffsetMinutes === null || body.checkInOpeningOffsetMinutes === undefined
        ? null
        : Number(body.checkInOpeningOffsetMinutes),
    presentWindowMinutes: Number(body.presentWindowMinutes),
    lateWindowMinutes: Number(body.lateWindowMinutes),
    autoCloseEnabled: body.autoCloseEnabled !== false,
    absenceThresholdPercent:
      body.absenceThresholdPercent === null || body.absenceThresholdPercent === undefined
        ? null
        : Number(body.absenceThresholdPercent),
    excusedCountsTowardThreshold: body.excusedCountsTowardThreshold === true,
    manualEditWindowHours: Number(body.manualEditWindowHours),
    adminApprovalRequired: body.adminApprovalRequired === true,
    gpsRequired,
    gpsRadiusMeters: gpsRequired ? Number(body.gpsRadiusMeters) : null,
    gpsMinAccuracyMeters:
      body.gpsMinAccuracyMeters === null || body.gpsMinAccuracyMeters === undefined
        ? null
        : Number(body.gpsMinAccuracyMeters),
    effectiveFrom: typeof body.effectiveFrom === "string" ? body.effectiveFrom : null,
    effectiveTo: typeof body.effectiveTo === "string" ? body.effectiveTo : null,
    fieldOverrides,
  };
}

/** BR-11 / BR-12 — Present vs Late from session open time and policy windows. */
export function resolveAttendanceStatus(
  openedAt: string,
  checkInAt: Date,
  policy: Pick<EffectivePolicyValues, "presentWindowMinutes" | "lateWindowMinutes">,
): "Present" | "Late" {
  const openedMs = new Date(openedAt).getTime();
  const elapsedMinutes = (checkInAt.getTime() - openedMs) / 60_000;
  if (elapsedMinutes <= policy.presentWindowMinutes) {
    return "Present";
  }
  return "Late";
}

export function isWithinManualEditWindow(
  closedAt: Date,
  windowHours: number,
  now: Date = new Date(),
): boolean {
  const deadline = new Date(closedAt.getTime() + windowHours * 60 * 60 * 1000);
  return now.getTime() <= deadline.getTime();
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

/** FR-35 / BR-08–BR-10 — GPS payload validation (radius checked separately when room known). */
export function evaluateGpsPayload(
  gps: GpsPayload | null | undefined,
  policy: Pick<EffectivePolicyValues, "gpsRequired" | "gpsMinAccuracyMeters">,
): GpsValidationOutcome {
  if (!policy.gpsRequired) return null;

  if (!gps) return "GpsRequired";
  if (gps.permissionDenied) return "GpsDisabled";

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

  return null;
}

export function evaluateGpsDistance(
  gps: GpsPayload,
  room: { latitude: number; longitude: number },
  allowedRadiusMeters: number,
): { outcome: "OutOfRadius" | null; distanceMeters: number } {
  const distanceMeters = haversineMeters(
    gps.latitude,
    gps.longitude,
    room.latitude,
    room.longitude,
  );
  if (distanceMeters > allowedRadiusMeters) {
    return { outcome: "OutOfRadius", distanceMeters };
  }
  return { outcome: null, distanceMeters };
}
