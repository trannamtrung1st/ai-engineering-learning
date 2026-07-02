import type { AttendanceStatus } from "../../components/ui/StatusBadge";
import { formatCheckInTimestamp } from "./format-timestamp";

export interface DuplicatePriorStatusInput {
  attendanceStatus?: string;
  checkInAt?: string;
}

export interface DuplicatePriorStatus {
  attendanceStatus: AttendanceStatus;
  timestamp: string;
}

const DUPLICATE_PRIOR_STATUSES = new Set<AttendanceStatus>([
  "Present",
  "Late",
  "Manual Present",
]);

function isDuplicatePriorStatus(status: string): status is AttendanceStatus {
  return DUPLICATE_PRIOR_STATUSES.has(status as AttendanceStatus);
}

export function resolveDuplicatePriorStatus(
  details?: DuplicatePriorStatusInput | null,
): DuplicatePriorStatus | null {
  if (!details?.attendanceStatus || !isDuplicatePriorStatus(details.attendanceStatus)) {
    return null;
  }
  if (!details.checkInAt) {
    return null;
  }
  return {
    attendanceStatus: details.attendanceStatus,
    timestamp: formatCheckInTimestamp(details.checkInAt),
  };
}
