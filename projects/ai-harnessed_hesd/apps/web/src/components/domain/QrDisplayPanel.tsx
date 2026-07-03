import { QRCodeSVG } from "qrcode.react";
import { useCallback, useEffect, useState } from "react";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { SessionStatusBadge, type SessionState } from "../ui/StatusBadge";
import { QrCountdownRing } from "./QrCountdownRing";
import styles from "./QrDisplayPanel.module.css";

/** Minimum QR canvas height for 1280×720 projector legibility (≥60% viewport). AC-UI-06 NFR-15 */
export const PROJECTION_QR_SIZE = 432;

export interface QrDisplayData {
  qrPayload: string;
  expiresAt: string;
  tokenState: "Valid" | "Expired" | "Invalid";
}

export interface QrDisplayPanelProps {
  sectionCode: string;
  sessionName: string;
  sessionState: SessionState;
  qrData: QrDisplayData | null;
  errorMessage?: string | null;
  projectionMode?: boolean;
  onRefresh?: () => void;
  onExpire?: () => void;
}

export function QrDisplayPanel({
  sectionCode,
  sessionName,
  sessionState,
  qrData,
  errorMessage,
  projectionMode = false,
  onRefresh,
  onExpire,
}: QrDisplayPanelProps) {
  const [fadeKey, setFadeKey] = useState(0);

  useEffect(() => {
    if (qrData?.qrPayload) {
      setFadeKey((value) => value + 1);
    }
  }, [qrData?.qrPayload, qrData?.expiresAt]);

  const handleExpire = useCallback(() => {
    onExpire?.();
  }, [onExpire]);

  const showQr = sessionState === "Open" && qrData?.tokenState === "Valid" && qrData.qrPayload;

  return (
    <Card
      className={[styles.panel, projectionMode ? styles.projection : ""].filter(Boolean).join(" ")}
      elevated
    >
      <header className={styles.header}>
        <div className={styles.identity}>
          <p className={styles.sectionCode}>{sectionCode}</p>
          <h2 className={styles.sessionName}>{sessionName}</h2>
        </div>
        <div className={styles.statusRow}>
          <SessionStatusBadge state={sessionState} />
          {showQr && qrData ? (
            <QrCountdownRing expiresAt={qrData.expiresAt} onExpire={handleExpire} />
          ) : null}
        </div>
      </header>

      {errorMessage ? (
        <FeedbackAlert variant="danger" title="Không thể tải mã QR">
          {errorMessage}
        </FeedbackAlert>
      ) : null}

      {showQr && qrData ? (
        <div className={styles.qrRegion} key={fadeKey}>
          <QRCodeSVG
            value={qrData.qrPayload}
            size={projectionMode ? PROJECTION_QR_SIZE : 280}
            bgColor="#ffffff"
            fgColor="#000000"
            level="M"
            includeMargin={false}
            className={styles.qrCanvas}
            data-testid="qr-display-canvas"
          />
        </div>
      ) : (
        <div className={styles.lockedState} role="status">
          <p className={styles.lockedTitle}>
            {sessionState === "Closed"
              ? "Buổi học đã đóng — mã QR không còn hiệu lực"
              : sessionState === "Cancelled"
                ? "Buổi học đã hủy — mã QR bị khóa"
                : "Mã QR chưa sẵn sàng — mở buổi học để hiển thị"}
          </p>
          <p className={styles.lockedHint}>
            Sinh viên chỉ có thể quét khi trạng thái buổi học là Đang mở.
          </p>
        </div>
      )}

      {onRefresh ? (
        <div className={styles.actions}>
          <Button variant="secondary" onClick={onRefresh}>
            Làm mới mã QR
          </Button>
        </div>
      ) : null}
    </Card>
  );
}
