import { AttendanceStatus } from "@wecheck/domain";
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  patchAttendanceRecord,
  type RosterRecord,
} from "@/lib/attendance-roster-api";
import { attendanceStatusLabels } from "@/lib/copy/status-labels";

const MANUAL_STATUSES = [
  AttendanceStatus.Present,
  AttendanceStatus.Absent,
  AttendanceStatus.Excused,
  AttendanceStatus.Rejected,
] as const;

const NOTE_REQUIRED_STATUSES = new Set<AttendanceStatus>([
  AttendanceStatus.Excused,
  AttendanceStatus.Rejected,
]);

function initialEditStatus(current: AttendanceStatus): AttendanceStatus {
  if ((MANUAL_STATUSES as readonly AttendanceStatus[]).includes(current)) {
    return current;
  }
  return AttendanceStatus.Present;
}

export interface AttendanceEditDialogProps {
  open: boolean;
  record: RosterRecord | null;
  editAllowed: boolean;
  windowExpired: boolean;
  hoursRemaining: number | null;
  onClose: () => void;
  onSaved: (record: RosterRecord, note: string) => void;
}

/** FR-11 / BR-10 / AC-11 — manual attendance correction dialog */
export function AttendanceEditDialog({
  open,
  record,
  editAllowed,
  windowExpired,
  hoursRemaining,
  onClose,
  onSaved,
}: AttendanceEditDialogProps) {
  const [status, setStatus] = useState<AttendanceStatus>(AttendanceStatus.Present);
  const [note, setNote] = useState("");
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || !record) return;
    setStatus(initialEditStatus(record.status as AttendanceStatus));
    setNote("");
    setFieldError(null);
    setFormError(null);
  }, [open, record]);

  const handleClose = useCallback(() => {
    if (submitting) return;
    onClose();
  }, [onClose, submitting]);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        handleClose();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    panelRef.current?.focus();
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, handleClose]);

  if (!open || !record) return null;

  const disabled = !editAllowed || windowExpired;

  function validate(): boolean {
    if (NOTE_REQUIRED_STATUSES.has(status)) {
      const trimmed = note.trim();
      if (trimmed.length < 10) {
        setFieldError("Ghi chú phải có ít nhất 10 ký tự");
        return false;
      }
      if (trimmed.length > 500) {
        setFieldError("Ghi chú không được vượt quá 500 ký tự");
        return false;
      }
    }
    setFieldError(null);
    return true;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (disabled || !record || !validate()) return;

    setSubmitting(true);
    setFormError(null);

    const currentRecord = record;
    const trimmedNote = note.trim();
    const result = await patchAttendanceRecord(currentRecord.id, {
      status,
      ...(trimmedNote ? { note: trimmedNote } : {}),
    });

    setSubmitting(false);

    if (!result.ok) {
      setFormError(result.error.message ?? "Không thể cập nhật điểm danh");
      return;
    }

    onSaved(
      {
        ...currentRecord,
        status: result.data.status,
        checkedInAt: result.data.checkedInAt,
      },
      trimmedNote,
    );
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      data-testid="attendance-edit-dialog-overlay"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="attendance-edit-title"
        tabIndex={-1}
        className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg"
        data-testid="attendance-edit-dialog"
      >
        <h2 id="attendance-edit-title" className="text-h2 font-semibold">
          Chỉnh sửa điểm danh
        </h2>

        <p className="mt-2 text-body text-text-secondary">
          Sinh viên: <span className="font-medium text-text-primary">{record.displayName}</span>
        </p>

        <div className="mt-3 flex items-center gap-2">
          <span className="text-small text-text-secondary">Trạng thái hiện tại:</span>
          <StatusBadge status={record.status as AttendanceStatus} size="sm" />
        </div>

        {windowExpired ? (
          <div data-testid="edit-window-expired-notice">
            <Alert variant="warning" title="Đã hết thời hạn chỉnh sửa điểm danh" className="mt-4">
              Liên hệ phòng đào tạo để chỉnh sửa.
            </Alert>
          </div>
        ) : null}

        {!windowExpired && hoursRemaining !== null && hoursRemaining > 0 ? (
          <p
            className="mt-4 rounded-md bg-warning-50 px-3 py-2 text-small text-warning-800"
            data-testid="edit-window-countdown"
          >
            Còn {hoursRemaining} giờ để chỉnh sửa
          </p>
        ) : null}

        {formError ? (
          <Alert variant="danger" title="Lỗi" className="mt-4">
            {formError}
          </Alert>
        ) : null}

        <form className="mt-4 flex flex-col gap-4" onSubmit={(e) => void handleSubmit(e)}>
          <div>
            <label htmlFor="attendance-edit-status" className="mb-1 block text-small font-medium">
              Trạng thái mới <span className="text-danger-600">*</span>
            </label>
            <select
              id="attendance-edit-status"
              className="w-full rounded-md border border-border bg-surface px-3 py-2 text-body"
              value={status}
              disabled={disabled || submitting}
              aria-required="true"
              data-testid="attendance-edit-status"
              onChange={(event) => setStatus(event.target.value as AttendanceStatus)}
            >
              {MANUAL_STATUSES.map((value) => (
                <option key={value} value={value}>
                  {attendanceStatusLabels[value]}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label htmlFor="attendance-edit-note" className="mb-1 block text-small font-medium">
              Ghi chú
              {NOTE_REQUIRED_STATUSES.has(status) ? (
                <span className="text-danger-600"> *</span>
              ) : null}
            </label>
            <textarea
              id="attendance-edit-note"
              className="min-h-[88px] w-full rounded-md border border-border bg-surface px-3 py-2 text-body"
              value={note}
              disabled={disabled || submitting}
              aria-invalid={fieldError ? "true" : undefined}
              aria-describedby={fieldError ? "attendance-edit-note-error" : undefined}
              data-testid="attendance-edit-note"
              onChange={(event) => {
                setNote(event.target.value);
                setFieldError(null);
              }}
            />
            {fieldError ? (
              <p
                id="attendance-edit-note-error"
                role="alert"
                className="mt-1 text-small text-danger-600"
              >
                {fieldError}
              </p>
            ) : null}
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              disabled={submitting}
              onClick={handleClose}
            >
              Hủy
            </Button>
            <Button
              type="submit"
              disabled={disabled || submitting}
              aria-busy={submitting}
              data-testid="attendance-edit-submit"
            >
              {submitting ? <Spinner className="h-4 w-4" /> : "Cập nhật điểm danh"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
