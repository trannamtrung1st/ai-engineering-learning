import { useEffect, useId, useRef, useState } from "react";
import { AttendanceStatusCell } from "./AttendanceStatusCell";
import { Button } from "../ui/Button";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import {
  patchAttendanceCorrection,
  type CorrectionPayload,
  type RosterRow,
} from "../../lib/api/roster-api";
import styles from "./ManualCorrectionDialog.module.css";

const CORRECTABLE_STATUSES = [
  { value: "Manual Present", label: "Có mặt (thủ công)" },
  { value: "Present", label: "Có mặt" },
  { value: "Late", label: "Đi trễ" },
  { value: "Excused", label: "Có phép" },
  { value: "Absent", label: "Vắng" },
] as const;

export interface ManualCorrectionDialogProps {
  sessionId: string;
  row: RosterRow;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function ManualCorrectionDialog({
  sessionId,
  row,
  open,
  onClose,
  onSuccess,
}: ManualCorrectionDialogProps) {
  const titleId = useId();
  const reasonId = useId();
  const statusId = useId();
  const triggerRef = useRef<HTMLElement | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState("Manual Present");
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [escalation, setEscalation] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) return;
    setStatus(
      row.attendanceStatus === "Pending" || row.attendanceStatus === "Absent"
        ? "Manual Present"
        : row.attendanceStatus,
    );
    setReason("");
    setReasonError(null);
    setSubmitError(null);
    setEscalation(false);
    const active = document.activeElement;
    if (active instanceof HTMLElement) {
      triggerRef.current = active;
    }
    dialogRef.current?.querySelector<HTMLElement>("select, textarea, button")?.focus();
  }, [open, row.attendanceStatus]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  const handleClose = () => {
    onClose();
    triggerRef.current?.focus();
  };

  const validateReason = (value: string): boolean => {
    if (value.trim().length < 8) {
      setReasonError("Vui lòng nhập lý do tối thiểu 8 ký tự.");
      return false;
    }
    setReasonError(null);
    return true;
  };

  const handleSubmit = async () => {
    if (!validateReason(reason)) return;
    setSubmitting(true);
    setSubmitError(null);
    setEscalation(false);

    const payload: CorrectionPayload = { status, reason: reason.trim() };
    const result = await patchAttendanceCorrection(sessionId, row.studentUserId, payload);

    if (result.ok) {
      onSuccess();
      handleClose();
      setSubmitting(false);
      return;
    }

    if (result.code === "EditWindowExpired") {
      setEscalation(true);
      setSubmitError(null);
    } else if (result.code === "OutOfScope" || result.code === "Forbidden") {
      setSubmitError("Bạn không có quyền thực hiện thao tác này.");
    } else if (result.code === "ReasonRequired") {
      setReasonError("Lý do là bắt buộc cho điều chỉnh thủ công.");
    } else {
      setSubmitError(result.message);
    }
    setSubmitting(false);
  };

  if (!open) return null;

  return (
    <div className={styles.overlay} role="presentation" onMouseDown={handleClose}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(event) => event.stopPropagation()}
        data-testid="manual-correction-dialog"
      >
        <header className={styles.header}>
          <h2 id={titleId} className={styles.title}>
            Điều chỉnh điểm danh
          </h2>
          <Button variant="ghost" size="sm" type="button" onClick={handleClose} aria-label="Đóng">
            ✕
          </Button>
        </header>

        <div className={styles.body}>
          <p className={styles.identity}>
            <strong>{row.displayName}</strong> · {row.studentCode}
          </p>
          <div>
            <span className={styles.label}>Trạng thái hiện tại</span>
            <AttendanceStatusCell status={row.attendanceStatus} method={row.checkInMethod} />
          </div>

          {escalation ? (
            <FeedbackAlert variant="warning" title="Hết thời gian chỉnh sửa">
              <p className={styles.escalation}>
                Thời gian chỉnh sửa thủ công đã hết. Vui lòng liên hệ Quản trị học vụ để xử lý
                ngoại lệ.
              </p>
            </FeedbackAlert>
          ) : null}

          {submitError ? (
            <FeedbackAlert variant="danger" title="Không thể lưu">
              {submitError}
            </FeedbackAlert>
          ) : null}

          <label className={styles.field} htmlFor={statusId}>
            <span className={styles.label}>Trạng thái mới</span>
            <select
              id={statusId}
              className={styles.select}
              value={status}
              disabled={escalation || submitting}
              onChange={(event) => setStatus(event.target.value)}
            >
              {CORRECTABLE_STATUSES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className={styles.field} htmlFor={reasonId}>
            <span className={styles.label}>Lý do</span>
            <textarea
              id={reasonId}
              className={styles.textarea}
              value={reason}
              disabled={escalation || submitting}
              aria-invalid={Boolean(reasonError)}
              aria-describedby={reasonError ? `${reasonId}-error` : undefined}
              placeholder="Mô tả lý do điều chỉnh sau khi xác minh trực tiếp…"
              onChange={(event) => {
                setReason(event.target.value);
                if (reasonError) validateReason(event.target.value);
              }}
            />
            {reasonError ? (
              <p id={`${reasonId}-error`} className={styles.fieldError} role="alert">
                {reasonError}
              </p>
            ) : null}
          </label>
        </div>

        <footer className={styles.footer}>
          <Button variant="secondary" type="button" onClick={handleClose} disabled={submitting}>
            Hủy
          </Button>
          <Button
            type="button"
            disabled={escalation || submitting || reason.trim().length < 8}
            onClick={() => void handleSubmit()}
          >
            {submitting ? "Đang lưu…" : "Lưu điều chỉnh"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
