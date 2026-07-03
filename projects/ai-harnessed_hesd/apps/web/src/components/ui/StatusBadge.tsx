import styles from "./StatusBadge.module.css";

export type StatusBadgeVariant =
  | "brand"
  | "alternative"
  | "gray"
  | "success"
  | "danger"
  | "warning"
  | "dark";

export type SessionState = "Scheduled" | "Open" | "Closed" | "Cancelled";
export type AttendanceStatus =
  | "Present"
  | "Late"
  | "Absent"
  | "Pending"
  | "Excused"
  | "Manual Present";

export interface StatusBadgeProps {
  label: string;
  variant?: StatusBadgeVariant;
  pill?: boolean;
  className?: string;
}

const sessionVariantMap: Record<SessionState, StatusBadgeVariant> = {
  Scheduled: "gray",
  Open: "success",
  Closed: "dark",
  Cancelled: "danger",
};

const attendanceVariantMap: Record<AttendanceStatus, StatusBadgeVariant> = {
  Present: "success",
  "Manual Present": "success",
  Late: "warning",
  Absent: "danger",
  Pending: "brand",
  Excused: "alternative",
};

export function sessionBadgeVariant(state: SessionState): StatusBadgeVariant {
  return sessionVariantMap[state];
}

export function attendanceBadgeVariant(status: AttendanceStatus): StatusBadgeVariant {
  return attendanceVariantMap[status];
}

export function StatusBadge({
  label,
  variant = "alternative",
  pill = false,
  className,
}: StatusBadgeProps) {
  const classes = [
    styles.badge,
    styles[`variant-${variant}`],
    pill ? styles.pill : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return <span className={classes}>{label}</span>;
}

export function SessionStatusBadge({ state }: { state: SessionState }) {
  const labels: Record<SessionState, string> = {
    Scheduled: "Đã lên lịch",
    Open: "Đang mở",
    Closed: "Đã đóng",
    Cancelled: "Đã hủy",
  };

  return (
    <StatusBadge
      label={labels[state]}
      variant={sessionBadgeVariant(state)}
      pill
    />
  );
}
