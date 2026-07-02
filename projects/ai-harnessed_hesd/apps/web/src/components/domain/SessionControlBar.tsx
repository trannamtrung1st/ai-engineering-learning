import { Button } from "../ui/Button";
import type { SessionState } from "../ui/StatusBadge";
import styles from "./SessionControlBar.module.css";

export interface SessionControlBarProps {
  roomName: string;
  scheduledAt: string;
  sessionState: SessionState;
  onOpen?: () => void;
  onClose?: () => void;
  loading?: boolean;
  className?: string;
}

export function SessionControlBar({
  roomName,
  scheduledAt,
  sessionState,
  onOpen,
  onClose,
  loading = false,
  className,
}: SessionControlBarProps) {
  return (
    <div className={[styles.bar, className ?? ""].filter(Boolean).join(" ")}>
      <div className={styles.meta}>
        <p className={styles.detail}>
          {roomName} · {scheduledAt}
        </p>
      </div>
      <div className={styles.actions}>
        {sessionState === "Scheduled" ? (
          <Button onClick={onOpen} disabled={loading}>
            Mở điểm danh
          </Button>
        ) : null}
        {sessionState === "Open" ? (
          <Button variant="danger" onClick={onClose} disabled={loading}>
            Đóng điểm danh
          </Button>
        ) : null}
      </div>
    </div>
  );
}
