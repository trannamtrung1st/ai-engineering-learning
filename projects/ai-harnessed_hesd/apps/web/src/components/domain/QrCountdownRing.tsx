import { useEffect, useMemo, useState } from "react";
import styles from "./QrCountdownRing.module.css";

const TTL_SECONDS = 30;
const WARNING_THRESHOLD = 5;

export interface QrCountdownRingProps {
  expiresAt: string;
  onExpire?: () => void;
  className?: string;
}

function secondsRemaining(expiresAt: string, nowMs: number): number {
  const delta = Math.ceil((new Date(expiresAt).getTime() - nowMs) / 1000);
  return Math.max(0, delta);
}

export function QrCountdownRing({ expiresAt, onExpire, className }: QrCountdownRingProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  const remaining = useMemo(() => secondsRemaining(expiresAt, nowMs), [expiresAt, nowMs]);

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 250);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (remaining === 0) {
      onExpire?.();
    }
  }, [remaining, onExpire]);

  const progress = Math.min(1, remaining / TTL_SECONDS);
  const warning = remaining > 0 && remaining <= WARNING_THRESHOLD;
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - progress);

  return (
    <div
      className={[styles.ring, warning ? styles.warning : "", className ?? ""]
        .filter(Boolean)
        .join(" ")}
      aria-live="polite"
      aria-label={`Còn ${remaining} giây`}
    >
      <svg className={styles.svg} viewBox="0 0 100 100" role="img" aria-hidden="true">
        <circle className={styles.track} cx="50" cy="50" r={radius} />
        <circle
          className={styles.progress}
          cx="50"
          cy="50"
          r={radius}
          style={{
            strokeDasharray: `${circumference}`,
            strokeDashoffset: dashOffset,
          }}
        />
      </svg>
      <span className={styles.label}>{remaining}s</span>
      <span className="sr-only">Còn {remaining} giây</span>
    </div>
  );
}

export { TTL_SECONDS, WARNING_THRESHOLD };
