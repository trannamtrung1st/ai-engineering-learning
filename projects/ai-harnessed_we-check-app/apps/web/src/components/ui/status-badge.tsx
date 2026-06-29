import {
  AttendanceStatus,
  SessionStatus,
  type AttendanceStatus as AttendanceStatusType,
  type SessionStatus as SessionStatusType,
} from "@wecheck/domain";
import { cn } from "@/lib/cn";
import {
  attendanceStatusLabels,
  sessionStatusLabels,
} from "@/lib/copy/status-labels";

type StatusValue = SessionStatusType | AttendanceStatusType;

const sessionStyles: Record<SessionStatusType, string> = {
  [SessionStatus.Draft]:
    "bg-surface-raised text-text-secondary border-border",
  [SessionStatus.Active]:
    "bg-success-50 text-success-500 border-success-500",
  [SessionStatus.Closed]:
    "bg-surface-raised text-text-secondary border-border",
  [SessionStatus.Cancelled]:
    "bg-danger-50 text-danger-500 border-danger-500 border-dashed",
};

const attendanceStyles: Record<AttendanceStatusType, string> = {
  [AttendanceStatus.Pending]:
    "bg-warning-50 text-warning-500 border-warning-500",
  [AttendanceStatus.Present]:
    "bg-success-50 text-success-500 border-success-500",
  [AttendanceStatus.Absent]:
    "bg-danger-50 text-danger-500 border-danger-500",
  [AttendanceStatus.Excused]:
    "bg-info-50 text-info-500 border-info-500",
  [AttendanceStatus.Rejected]:
    "bg-danger-50 text-danger-500 border-danger-500",
};

function isSessionStatus(status: StatusValue): status is SessionStatusType {
  return status in sessionStatusLabels;
}

function getStatusLabel(status: StatusValue): string {
  return isSessionStatus(status)
    ? sessionStatusLabels[status]
    : attendanceStatusLabels[status];
}

function getStatusStyle(status: StatusValue): string {
  return isSessionStatus(status)
    ? sessionStyles[status]
    : attendanceStyles[status];
}

export interface StatusBadgeProps {
  status: StatusValue;
  size?: "sm" | "md";
  className?: string;
}

export function StatusBadge({
  status,
  size = "md",
  className,
}: StatusBadgeProps) {
  return (
    <span
      data-testid={`status-badge-${status}`}
      className={cn(
        "inline-flex items-center rounded-full border font-medium",
        size === "sm" ? "px-2 py-0.5 text-small" : "px-2.5 py-1 text-small",
        getStatusStyle(status),
        className,
      )}
    >
      {getStatusLabel(status)}
    </span>
  );
}
