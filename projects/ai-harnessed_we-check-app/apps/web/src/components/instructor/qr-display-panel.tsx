import { SessionStatus } from "@wecheck/domain";
import { Link } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { QrCodeImage } from "@/components/ui/qr-code-image";
import { QrCountdown } from "@/components/ui/qr-countdown";
import { useQrDisplayCycle } from "@/hooks/use-qr-display-cycle";

export interface QrDisplayPanelProps {
  sessionId: string;
  sessionStatus: SessionStatus;
  classCode?: string;
  subjectCode?: string;
  roomName?: string;
}

function SessionNotActiveState({ sessionStatus }: { sessionStatus: SessionStatus }) {
  const isDraft = sessionStatus === SessionStatus.Draft;

  return (
    <div className="py-8 text-center" data-testid="session-not-active">
      <div
        className="mx-auto mb-4 flex h-32 w-32 items-center justify-center rounded-full bg-surface-sunken text-4xl text-text-secondary"
        aria-hidden="true"
      >
        QR
      </div>
      <p className="text-body text-text-secondary">
        {isDraft ? "Buổi học chưa mở" : "Buổi học đã kết thúc"}
      </p>
      {!isDraft ? (
        <p className="mt-2 text-small text-text-secondary">
          Mã QR không còn hiển thị khi buổi học đã đóng.
        </p>
      ) : null}
    </div>
  );
}

/** FR-06 / AC-06 / NFR-20 — instructor QR tab preview with countdown and fullscreen launch */
export function QrDisplayPanel({
  sessionId,
  sessionStatus,
  classCode,
  subjectCode,
  roomName,
}: QrDisplayPanelProps) {
  const isActive = sessionStatus === SessionStatus.Active;
  const { qrQuery, liveToken, secondsRemaining, tokenKey, fading } =
    useQrDisplayCycle(sessionId, isActive);

  if (!isActive) {
    return <SessionNotActiveState sessionStatus={sessionStatus} />;
  }

  if (qrQuery.isError) {
    return (
      <div className="py-6" data-testid="qr-display-error">
        <Alert variant="danger" title="Không thể tải mã QR">
          Không thể lấy mã QR hiện tại. Vui lòng thử lại.
        </Alert>
        <Button
          type="button"
          variant="outline"
          className="mt-4"
          onClick={() => void qrQuery.refetch()}
        >
          Thử lại
        </Button>
      </div>
    );
  }

  const metaParts = [classCode, subjectCode, roomName].filter(Boolean);

  return (
    <div
      className="flex flex-col items-center gap-6 py-6"
      data-testid="qr-display-panel"
    >
      {metaParts.length > 0 ? (
        <p className="text-small text-text-secondary" data-testid="qr-session-meta">
          {metaParts.join(" · ")}
        </p>
      ) : null}

      <div className="rounded-lg bg-surface-inverse p-4">
        <QrCodeImage
          value={liveToken?.qrPayload}
          variant="preview"
          fading={fading}
          imageKey={tokenKey}
          tokenId={liveToken?.tokenId}
        />
      </div>

      <QrCountdown secondsRemaining={secondsRemaining} />

      <p className="text-small text-text-secondary">Quét mã để điểm danh</p>

      <Link
        to={`/sessions/${sessionId}/qr-present`}
        className="inline-flex min-h-touch items-center justify-center rounded-md border border-border bg-surface-raised px-4 font-medium hover:bg-primary-50"
        data-testid="qr-present-link"
      >
        Trình chiếu QR
      </Link>
    </div>
  );
}
