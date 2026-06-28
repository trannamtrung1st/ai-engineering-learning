import {
  canManualEditAttendance,
  isWithinInstructorEditWindow,
  type UserRole,
} from "@wecheck/domain";
import type { SessionStatus } from "@wecheck/domain";

export { canManualEditAttendance, isWithinInstructorEditWindow };

export interface EditWindowPolicyInput {
  editorRole: UserRole;
  sessionStatus: SessionStatus;
  closedAt: Date | null;
  now: Date;
}

/** BR-10 — instructor 24 h window after close; admin unlimited; Active always editable. */
export function assertManualEditAllowed(input: EditWindowPolicyInput): boolean {
  return canManualEditAttendance(input);
}
