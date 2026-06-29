import { AttendanceStatus } from "../enums.js";

/**
 * BR-04 — blocks automated duplicate check-in when student already checked in.
 * Present always blocks; Excused blocks only when a prior check-in timestamp exists.
 */
export function blocksDuplicateCheckIn(
  status: AttendanceStatus,
  checkedInAt: Date | null,
): boolean {
  if (status === AttendanceStatus.Present) {
    return true;
  }
  if (status === AttendanceStatus.Excused && checkedInAt !== null) {
    return true;
  }
  return false;
}
