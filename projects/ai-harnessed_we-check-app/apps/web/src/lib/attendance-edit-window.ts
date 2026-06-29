import {
  INSTRUCTOR_EDIT_WINDOW_MS,
  SessionStatus,
  UserRole,
  canManualEditAttendance,
  type UserRole as UserRoleType,
} from "@wecheck/domain";

export interface EditWindowContext {
  editorRole: UserRoleType;
  sessionStatus: SessionStatus;
  closedAt: string | null;
}

/** BR-10 — whether manual edit is permitted for current editor */
export function isAttendanceEditAllowed(ctx: EditWindowContext, now = new Date()): boolean {
  return canManualEditAttendance({
    editorRole: ctx.editorRole,
    sessionStatus: ctx.sessionStatus,
    closedAt: ctx.closedAt ? new Date(ctx.closedAt) : null,
    now,
  });
}

/** Hours remaining in instructor 24 h post-close window; null when not applicable */
export function instructorEditHoursRemaining(
  closedAt: string | null,
  now = new Date(),
): number | null {
  if (!closedAt) return null;
  const elapsed = now.getTime() - new Date(closedAt).getTime();
  const remainingMs = INSTRUCTOR_EDIT_WINDOW_MS - elapsed;
  if (remainingMs <= 0) return 0;
  return Math.ceil(remainingMs / (60 * 60 * 1000));
}

export function isInstructorRole(role: UserRoleType): boolean {
  return role === UserRole.Instructor;
}

export function isAdminRole(role: UserRoleType): boolean {
  return role === UserRole.TrainingOfficeAdmin;
}
