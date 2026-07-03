import { ErrorCode } from "@attendly/domain";
import type { ActorContext } from "../identity/types.js";
import {
  ATTENDANCE_STATUSES,
  CORRECTABLE_STATUSES,
  type AttendanceStatus,
  type CorrectableStatus,
  type EffectivePolicy,
} from "./types.js";

export type CorrectionValidationError =
  | { code: typeof ErrorCode.InvalidPayload }
  | { code: typeof ErrorCode.ReasonRequired }
  | { code: typeof ErrorCode.EditWindowExpired };

const SUCCESS_STATUSES = new Set<AttendanceStatus>(["Present", "Late", "Manual Present"]);

export function isAttendanceStatus(value: string): value is AttendanceStatus {
  return (ATTENDANCE_STATUSES as readonly string[]).includes(value);
}

export function isCorrectableStatus(value: string): value is CorrectableStatus {
  return (CORRECTABLE_STATUSES as readonly string[]).includes(value);
}

export function isSuccessfulAttendance(status: AttendanceStatus | null): boolean {
  return status !== null && SUCCESS_STATUSES.has(status);
}

export function isAdminOverrideRole(actor: ActorContext): boolean {
  return actor.roles.includes("AcademicAdmin") || actor.roles.includes("DepartmentAdmin");
}

export function resolveCheckInMethodForCorrection(actor: ActorContext): "Manual" | "Admin Correction" {
  return isAdminOverrideRole(actor) ? "Admin Correction" : "Manual";
}

export function isWithinManualEditWindow(
  closedAt: Date,
  windowHours: number,
  now: Date = new Date(),
): boolean {
  const deadline = new Date(closedAt.getTime() + windowHours * 60 * 60 * 1000);
  return now.getTime() <= deadline.getTime();
}

export function validateCorrectionPayload(body: {
  status?: unknown;
  reason?: unknown;
}): { ok: true; status: CorrectableStatus; reason: string } | { ok: false; error: CorrectionValidationError } {
  if (typeof body.status !== "string" || !isCorrectableStatus(body.status)) {
    return { ok: false, error: { code: ErrorCode.InvalidPayload } };
  }

  const reason = typeof body.reason === "string" ? body.reason.trim() : "";
  if (!reason) {
    return { ok: false, error: { code: ErrorCode.ReasonRequired } };
  }

  return { ok: true, status: body.status, reason };
}

export function validateCorrectionWindow(params: {
  actor: ActorContext;
  sessionState: string;
  closedAt: string | null;
  policy: EffectivePolicy;
  now?: Date;
}): { ok: true } | { ok: false; error: CorrectionValidationError } {
  if (isAdminOverrideRole(params.actor)) {
    return { ok: true };
  }

  if (!params.actor.roles.includes("Lecturer")) {
    return { ok: false, error: { code: ErrorCode.EditWindowExpired } };
  }

  if (params.sessionState === "Open") {
    return { ok: true };
  }

  if (params.sessionState === "Closed" && params.closedAt) {
    if (
      isWithinManualEditWindow(
        new Date(params.closedAt),
        params.policy.manualEditWindowHours,
        params.now,
      )
    ) {
      return { ok: true };
    }
    return { ok: false, error: { code: ErrorCode.EditWindowExpired } };
  }

  return { ok: false, error: { code: ErrorCode.EditWindowExpired } };
}
