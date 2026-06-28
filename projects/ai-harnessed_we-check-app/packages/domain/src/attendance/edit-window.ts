import { INSTRUCTOR_EDIT_WINDOW_MS } from "../constants.js";
import { SessionStatus, UserRole } from "../enums.js";

export interface ManualEditPolicyInput {
  editorRole: UserRole;
  sessionStatus: SessionStatus;
  closedAt: Date | null;
  now: Date;
}

/**
 * BR-10 — instructor edit within 24 h of closedAt; admin anytime.
 * Edits allowed when session is Active or Closed.
 */
export function canManualEditAttendance(input: ManualEditPolicyInput): boolean {
  if (
    input.sessionStatus !== SessionStatus.Active &&
    input.sessionStatus !== SessionStatus.Closed
  ) {
    return false;
  }

  if (input.editorRole === UserRole.TrainingOfficeAdmin) {
    return true;
  }

  if (input.editorRole !== UserRole.Instructor) {
    return false;
  }

  if (input.sessionStatus === SessionStatus.Active) {
    return true;
  }

  if (input.closedAt === null) {
    return false;
  }

  const elapsedMs = input.now.getTime() - input.closedAt.getTime();
  return elapsedMs <= INSTRUCTOR_EDIT_WINDOW_MS;
}

/** BR-10 — instructor window check for Closed sessions only. */
export function isWithinInstructorEditWindow(
  closedAt: Date,
  now: Date,
): boolean {
  return now.getTime() - closedAt.getTime() <= INSTRUCTOR_EDIT_WINDOW_MS;
}
