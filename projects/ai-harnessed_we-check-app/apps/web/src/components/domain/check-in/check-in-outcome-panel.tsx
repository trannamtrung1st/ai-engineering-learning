import {
  CalendarX,
  CheckCircle2,
  Clock,
  Info,
  MapPinOff,
  LocateOff,
  ShieldAlert,
  WifiOff,
  UserX,
  Ban,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import {
  type CheckInOutcomeCode,
  checkInOutcomeMessages,
} from "@/lib/copy/checkin-messages";
import { resolveOutcomeAction } from "@/lib/checkin-outcome";
import { cn } from "@/lib/cn";

const outcomeIcons: Record<CheckInOutcomeCode, LucideIcon> = {
  Present: CheckCircle2,
  ExpiredQr: Clock,
  TokenAlreadyUsed: Ban,
  OutOfRadius: MapPinOff,
  GpsDisabled: LocateOff,
  DuplicateCheckIn: Info,
  SpoofSuspected: ShieldAlert,
  SessionNotActive: CalendarX,
  NotEnrolled: UserX,
  NetworkError: WifiOff,
};

const buttonLinkClassName =
  "inline-flex w-full min-h-touch items-center justify-center gap-2 rounded-md bg-primary-600 px-4 py-3 text-body font-medium text-primary-foreground transition-colors hover:bg-primary-700 focus-visible:outline-none";

export interface CheckInOutcomePanelProps {
  outcome: CheckInOutcomeCode;
  detailMessage?: string;
  onAction?: () => void;
  onRetry?: () => void;
  className?: string;
}

/** NFR-17 — check-in outcome panel with Vietnamese messages per ui-states §4.3 */
export function CheckInOutcomePanel({
  outcome,
  detailMessage,
  onAction,
  onRetry,
  className,
}: CheckInOutcomePanelProps) {
  const copy = checkInOutcomeMessages[outcome];
  const Icon = outcomeIcons[outcome];
  const historyAction = resolveOutcomeAction(outcome) === "go_history";
  const historyHref = outcome === "DuplicateCheckIn" && historyAction ? "/history" : undefined;
  const useHistoryButton = outcome === "DuplicateCheckIn" && historyAction && Boolean(onAction);
  const showManualFallback = outcome !== "Present" && outcome !== "DuplicateCheckIn";
  const showGpsRetry = outcome === "GpsDisabled" && onRetry;

  return (
    <div
      data-testid={`check-in-outcome-${outcome}`}
      data-block-resubmit={outcome === "DuplicateCheckIn" ? "true" : undefined}
      className={cn("flex flex-col gap-4", className)}
    >
      <Alert variant={copy.variant} icon={Icon} title={copy.title}>
        {detailMessage ?? copy.message}
      </Alert>
      {useHistoryButton ? (
        <Button
          type="button"
          onClick={onAction}
          className="w-full min-h-touch"
          data-testid="duplicate-history-link"
        >
          {copy.cta}
        </Button>
      ) : historyHref ? (
        <Link
          to={historyHref}
          className={buttonLinkClassName}
          data-testid="duplicate-history-link"
        >
          {copy.cta}
        </Link>
      ) : (
        <Button type="button" onClick={onAction} className="w-full min-h-touch">
          {copy.cta}
        </Button>
      )}
      {showGpsRetry ? (
        <Button
          type="button"
          variant="outline"
          onClick={onRetry}
          className="w-full min-h-touch"
          data-testid="gps-retry-button"
        >
          Thử lại
        </Button>
      ) : null}
      {showManualFallback ? (
        <p className="text-small text-text-secondary" data-testid="manual-attendance-fallback">
          Nếu vẫn không điểm danh được, vui lòng liên hệ giảng viên để được ghi nhận thủ công.
        </p>
      ) : null}
    </div>
  );
}

/** Showcase all outcome variants for browser verification (NFR-17 TC-015) */
export function CheckInOutcomeShowcase() {
  const outcomes = Object.keys(checkInOutcomeMessages) as CheckInOutcomeCode[];

  return (
    <div className="flex flex-col gap-6" data-testid="check-in-outcome-showcase">
      {outcomes.map((outcome) => (
        <CheckInOutcomePanel key={outcome} outcome={outcome} />
      ))}
    </div>
  );
}
