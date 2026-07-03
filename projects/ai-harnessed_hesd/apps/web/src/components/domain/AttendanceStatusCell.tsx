import {
  StatusBadge,
  attendanceBadgeVariant,
  type AttendanceStatus,
} from "../ui/StatusBadge";
import styles from "./AttendanceStatusCell.module.css";

const ATTENDANCE_STATUSES = new Set<AttendanceStatus>([
  "Present",
  "Late",
  "Absent",
  "Pending",
  "Excused",
  "Manual Present",
]);

function isAttendanceStatus(value: string): value is AttendanceStatus {
  return ATTENDANCE_STATUSES.has(value as AttendanceStatus);
}

const statusLabels: Record<AttendanceStatus, string> = {
  Present: "Có mặt",
  "Manual Present": "Có mặt (thủ công)",
  Late: "Đi trễ",
  Absent: "Vắng",
  Pending: "Chưa điểm danh",
  Excused: "Có phép",
};

export interface AttendanceStatusCellProps {
  status: string;
  method?: string | null;
  compact?: boolean;
}

export function AttendanceStatusCell({ status, method, compact = false }: AttendanceStatusCellProps) {
  const normalized = isAttendanceStatus(status) ? status : "Pending";
  const methodLabel =
    method === "QR"
      ? "QR"
      : method === "Manual"
        ? "Thủ công"
        : method === "Admin Correction"
          ? "Admin"
          : null;

  return (
    <div className={[styles.cell, compact ? styles.compact : ""].filter(Boolean).join(" ")}>
      <StatusBadge
        label={statusLabels[normalized]}
        variant={attendanceBadgeVariant(normalized)}
        pill
      />
      {methodLabel ? (
        <span className={styles.method} aria-label={`Phương thức ${methodLabel}`}>
          {methodLabel}
        </span>
      ) : null}
    </div>
  );
}
