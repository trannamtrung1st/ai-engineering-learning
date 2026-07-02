import { Link } from "react-router-dom";
import { Button } from "../ui/Button";
import { SessionStatusBadge, type SessionState } from "../ui/StatusBadge";
import styles from "./SessionControlBar.module.css";

export interface SessionControlBarProps {
  sectionCode: string;
  roomName: string;
  scheduledAt: string;
  sessionState: SessionState;
  sessionId?: string;
  openedAt?: string | null;
  onOpen?: () => void;
  onClose?: () => void;
  loading?: boolean;
  className?: string;
}

export function SessionControlBar({
  sectionCode,
  roomName,
  scheduledAt,
  sessionState,
  sessionId,
  openedAt,
  onOpen,
  onClose,
  loading = false,
  className,
}: SessionControlBarProps) {
  const openedLabel =
    openedAt && sessionState === "Open"
      ? new Intl.DateTimeFormat("vi-VN", {
          hour: "2-digit",
          minute: "2-digit",
          day: "2-digit",
          month: "2-digit",
        }).format(new Date(openedAt))
      : null;

  return (
    <div
      className={[styles.bar, className ?? ""].filter(Boolean).join(" ")}
      data-testid="session-control-bar"
    >
      <div className={styles.meta}>
        <div className={styles.identityRow}>
          <p className={styles.code}>{sectionCode}</p>
          <SessionStatusBadge state={sessionState} />
        </div>
        <p className={styles.detail} data-testid="session-control-context">
          {roomName} · {scheduledAt}
        </p>
        {openedLabel ? (
          <p className={styles.openedAt} data-testid="session-opened-at">
            Lúc mở {openedLabel}
          </p>
        ) : null}
      </div>
      <div className={styles.actions}>
        {sessionState === "Scheduled" ? (
          <Button onClick={onOpen} disabled={loading}>
            Mở điểm danh
          </Button>
        ) : null}
        {sessionState === "Open" ? (
          <>
            <Button variant="danger" onClick={onClose} disabled={loading}>
              Đóng điểm danh
            </Button>
            {sessionId ? (
              <Link
                className={styles.rosterLink}
                to={`/lecturer/sessions/${sessionId}/roster`}
              >
                Xem danh sách
              </Link>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
