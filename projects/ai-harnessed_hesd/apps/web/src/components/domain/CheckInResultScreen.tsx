import { ErrorCode } from "@attendly/domain";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FeedbackAlert, type FeedbackAlertVariant } from "../ui/FeedbackAlert";
import { StatusBadge, attendanceBadgeVariant, type AttendanceStatus } from "../ui/StatusBadge";
import styles from "./CheckInResultScreen.module.css";

export type CheckInOutcomeState =
  | "success-present"
  | "success-late"
  | "failure-expired-qr"
  | "failure-not-enrolled"
  | "failure-duplicate"
  | "failure-session-not-open"
  | "failure-gps-denied"
  | "failure-out-of-radius"
  | "failure-unauthenticated";

export interface CheckInResultScreenProps {
  state: CheckInOutcomeState;
  title: string;
  message: string;
  timestamp?: string;
  attendanceStatus?: AttendanceStatus;
  retryAllowed?: boolean;
  onRetry?: () => void;
}

export function outcomeStateFromErrorCode(code: string): CheckInOutcomeState {
  switch (code) {
    case ErrorCode.ExpiredQr:
      return "failure-expired-qr";
    case ErrorCode.NotEnrolled:
      return "failure-not-enrolled";
    case ErrorCode.DuplicateCheckIn:
      return "failure-duplicate";
    case ErrorCode.SessionNotOpen:
    case ErrorCode.SessionClosed:
      return "failure-session-not-open";
    case ErrorCode.GpsDisabled:
    case ErrorCode.GpsRequired:
      return "failure-gps-denied";
    case ErrorCode.OutOfRadius:
    case ErrorCode.LowAccuracy:
      return "failure-out-of-radius";
    case ErrorCode.Unauthenticated:
      return "failure-unauthenticated";
    default:
      return "failure-session-not-open";
  }
}

function alertVariant(state: CheckInOutcomeState): FeedbackAlertVariant {
  if (state.startsWith("success")) {
    return state === "success-late" ? "warning" : "success";
  }
  if (state === "failure-duplicate") {
    return "info";
  }
  if (state === "failure-gps-denied" || state === "failure-out-of-radius") {
    return "warning";
  }
  return "danger";
}

export function CheckInResultScreen({
  state,
  title,
  message,
  timestamp,
  attendanceStatus,
  retryAllowed = false,
  onRetry,
}: CheckInResultScreenProps) {
  const success = state.startsWith("success");

  return (
    <Card className={styles.screen} elevated>
      {success ? (
        <div className={styles.success}>
          <h2 className={styles.title}>{title}</h2>
          <p className={styles.message}>{message}</p>
          {attendanceStatus ? (
            <StatusBadge
              label={attendanceStatusLabel(attendanceStatus)}
              variant={attendanceBadgeVariant(attendanceStatus)}
              pill
            />
          ) : null}
          {timestamp ? <p className={styles.timestamp}>Lúc {timestamp}</p> : null}
        </div>
      ) : (
        <FeedbackAlert
          title={title}
          variant={alertVariant(state)}
          action={
            retryAllowed && onRetry ? (
              <Button fullWidth onClick={onRetry}>
                Thử lại
              </Button>
            ) : null
          }
        >
          {message}
          {state === "failure-duplicate" && attendanceStatus && timestamp ? (
            <p className={styles.priorStatus}>
              Trạng thái hiện tại:{" "}
              <StatusBadge
                label={attendanceStatusLabel(attendanceStatus)}
                variant={attendanceBadgeVariant(attendanceStatus)}
                pill
              />{" "}
              · {timestamp}
            </p>
          ) : null}
        </FeedbackAlert>
      )}
    </Card>
  );
}

function attendanceStatusLabel(status: AttendanceStatus): string {
  const labels: Record<AttendanceStatus, string> = {
    Present: "Có mặt",
    "Manual Present": "Có mặt (thủ công)",
    Late: "Đi trễ",
    Absent: "Vắng",
    Pending: "Chờ xử lý",
    Excused: "Có phép",
  };
  return labels[status];
}
