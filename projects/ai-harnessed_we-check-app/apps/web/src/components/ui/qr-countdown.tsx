import { cn } from "@/lib/cn";
import { appCopy } from "@/lib/copy/status-labels";

export interface QrCountdownProps {
  secondsRemaining: number;
  className?: string;
  presentation?: boolean;
}

/** NFR-06 / NFR-20 — countdown with token color states per design tokens §3.4 */
export function QrCountdown({
  secondsRemaining,
  className,
  presentation = false,
}: QrCountdownProps) {
  const clamped = Math.max(0, Math.min(30, secondsRemaining));
  const isWarning = clamped <= 10;

  return (
    <p
      data-testid="qr-countdown"
      data-seconds-remaining={clamped}
      className={cn(
        presentation
          ? "text-[2rem] font-bold leading-10"
          : "text-h2 font-semibold",
        presentation && (isWarning ? "text-qr-warning" : "text-qr-countdown"),
        !presentation && isWarning && "text-qr-warning",
        !presentation && !isWarning && "text-qr-accent",
        className,
      )}
      aria-live="polite"
    >
      {appCopy.qrCountdownPrefix} {clamped} {appCopy.qrCountdownSuffix}
    </p>
  );
}
