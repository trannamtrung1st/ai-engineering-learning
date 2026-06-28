import { ATTENDANCE_WINDOW_MS } from "../constants.js";
import { SessionStatus } from "../enums.js";

export interface AttendanceWindowInput {
  status: SessionStatus;
  openedAt: Date | null;
  scheduledStart: Date;
  closedAt: Date | null;
  now: Date;
}

/** Nominal window end from scheduled start (BR-01). */
export function computeNominalWindowEnd(scheduledStart: Date): Date {
  return new Date(scheduledStart.getTime() + ATTENDANCE_WINDOW_MS);
}

/**
 * Effective attendance window end — earlier of manual close or nominal window.
 * @see docs/technical/07-state-machines.md §2.4
 */
export function computeAttendanceWindowEnd(
  scheduledStart: Date,
  closedAt: Date | null,
): Date {
  const nominalEnd = computeNominalWindowEnd(scheduledStart);
  if (closedAt === null) {
    return nominalEnd;
  }
  return closedAt.getTime() < nominalEnd.getTime() ? closedAt : nominalEnd;
}

/**
 * BR-01 — check-in allowed when session is Active and now is within the window.
 * Window: openedAt ≤ now ≤ min(closedAt, scheduledStart + 10 min).
 */
export function isWithinAttendanceWindow(input: AttendanceWindowInput): boolean {
  if (input.status !== SessionStatus.Active) {
    return false;
  }
  if (input.openedAt === null) {
    return false;
  }
  const windowStart = input.openedAt.getTime();
  const windowEnd = computeAttendanceWindowEnd(
    input.scheduledStart,
    input.closedAt,
  ).getTime();
  const now = input.now.getTime();
  return now >= windowStart && now <= windowEnd;
}

/** BR-01 — scheduler auto-close when now ≥ scheduledStart + 10 minutes. */
export function shouldAutoCloseSession(
  scheduledStart: Date,
  now: Date,
): boolean {
  return now.getTime() >= computeNominalWindowEnd(scheduledStart).getTime();
}
