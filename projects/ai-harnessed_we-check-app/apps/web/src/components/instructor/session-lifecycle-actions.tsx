import { SessionStatus, hasValidRoomGps } from "@wecheck/domain";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  cancelSession,
  closeSession,
  openSession,
  type SessionDetail,
} from "@/lib/sessions-api";

export interface SessionLifecycleActionsProps {
  session: SessionDetail;
  onSessionUpdated: (session: SessionDetail) => void;
}

/** FR-05 / BR-07 / AC-05 — session open, close, cancel lifecycle */
export function SessionLifecycleActions({
  session,
  onSessionUpdated,
}: SessionLifecycleActionsProps) {
  const [showOpenConfirm, setShowOpenConfirm] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const [showCancelConfirm, setShowCancelConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  const gpsValid = hasValidRoomGps({
    roomLatitude: session.roomLatitude,
    roomLongitude: session.roomLongitude,
  });

  async function handleOpen() {
    setLoading(true);
    const result = await openSession(session.id);
    setLoading(false);
    setShowOpenConfirm(false);
    if (!result.ok) {
      toast.error(result.error.message ?? "Không thể mở buổi học");
      return;
    }
    toast.success("Đã mở buổi học");
    onSessionUpdated({ ...session, ...result.data });
  }

  async function handleClose() {
    setLoading(true);
    const result = await closeSession(session.id);
    setLoading(false);
    setShowCloseConfirm(false);
    if (!result.ok) {
      toast.error(result.error.message ?? "Không thể đóng buổi học");
      return;
    }
    toast.success("Đã đóng buổi học");
    onSessionUpdated({ ...session, ...result.data });
  }

  async function handleCancel() {
    setLoading(true);
    const result = await cancelSession(session.id);
    setLoading(false);
    setShowCancelConfirm(false);
    if (!result.ok) {
      toast.error(result.error.message ?? "Không thể hủy buổi học");
      return;
    }
    toast.success("Đã hủy buổi học");
    onSessionUpdated({ ...session, ...result.data });
  }

  if (session.status === SessionStatus.Closed || session.status === SessionStatus.Cancelled) {
    return (
      <div data-testid="session-lifecycle-readonly">
        <Link
          to="/reports"
          className="text-body font-medium text-primary-700 hover:underline"
        >
          Xem báo cáo điểm danh
        </Link>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3" data-testid="session-lifecycle-actions">
      {session.status === SessionStatus.Draft ? (
        <>
          {!gpsValid ? (
            <div data-testid="gps-required-alert">
              <Alert variant="danger" title="Thiếu tọa độ GPS">
                Vui lòng cấu hình tọa độ phòng học trước khi mở buổi học
              </Alert>
            </div>
          ) : null}
          <Button
            type="button"
            disabled={!gpsValid || loading}
            data-testid="session-open-button"
            onClick={() => setShowOpenConfirm(true)}
          >
            Mở buổi học
          </Button>
          <Button
            type="button"
            variant="danger"
            disabled={loading}
            data-testid="session-cancel-button"
            onClick={() => setShowCancelConfirm(true)}
          >
            Hủy buổi học
          </Button>
        </>
      ) : null}

      {session.status === SessionStatus.Active ? (
        <>
          <Button
            type="button"
            disabled={loading}
            data-testid="session-close-button"
            onClick={() => setShowCloseConfirm(true)}
          >
            Đóng buổi học
          </Button>
          <Link
            to={`/sessions/${session.id}/qr-present`}
            className="inline-flex min-h-touch items-center justify-center rounded-md border border-border bg-surface-raised px-4 font-medium hover:bg-primary-50"
          >
            Trình chiếu QR
          </Link>
        </>
      ) : null}

      {showOpenConfirm ? (
        <ConfirmDialog
          title="Xác nhận mở buổi học?"
          description="Sau khi mở, sinh viên có thể bắt đầu điểm danh bằng mã QR."
          confirmLabel="Mở buổi học"
          onCancel={() => setShowOpenConfirm(false)}
          onConfirm={() => void handleOpen()}
        />
      ) : null}

      {showCloseConfirm ? (
        <ConfirmDialog
          title="Kết thúc điểm danh?"
          description="Sinh viên chưa điểm danh sẽ được ghi nhận vắng mặt."
          confirmLabel="Đóng buổi học"
          onCancel={() => setShowCloseConfirm(false)}
          onConfirm={() => void handleClose()}
        />
      ) : null}

      {showCancelConfirm ? (
        <ConfirmDialog
          title="Hủy buổi học?"
          description="Buổi học sẽ chuyển sang trạng thái Đã hủy và không thể mở lại."
          confirmLabel="Hủy buổi học"
          danger
          onCancel={() => setShowCancelConfirm(false)}
          onConfirm={() => void handleCancel()}
        />
      ) : null}
    </div>
  );
}

function ConfirmDialog({
  title,
  description,
  confirmLabel,
  danger,
  onCancel,
  onConfirm,
}: {
  title: string;
  description: string;
  confirmLabel: string;
  danger?: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg">
        <h2 className="text-h2 font-semibold">{title}</h2>
        <p className="mt-2 text-body text-text-secondary">{description}</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            Hủy
          </Button>
          <Button
            type="button"
            variant={danger ? "danger" : "primary"}
            data-testid="confirm-dialog-accept"
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
