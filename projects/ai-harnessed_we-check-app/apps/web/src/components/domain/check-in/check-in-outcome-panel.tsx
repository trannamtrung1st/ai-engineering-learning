import {
  CalendarX,
  CheckCircle2,
  Clock,
  History,
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
  DuplicateCheckIn: History,
  SpoofSuspected: ShieldAlert,
  SessionNotActive: CalendarX,
  NotEnrolled: UserX,
  NetworkError: WifiOff,
};

const washClasses = {
  success: "bg-success-50 border-success-500/20 text-text-primary",
  warning: "bg-warning-50 border-warning-500/20 text-text-primary",
  danger: "bg-danger-50 border-danger-500/20 text-text-primary",
  info: "bg-info-50 border-info-500/20 text-text-primary",
} as const;

const iconColorClasses = {
  success: "text-success-500",
  warning: "text-warning-500",
  danger: "text-danger-500",
  info: "text-info-500",
} as const;

const buttonLinkClassName =
  "inline-flex w-full min-h-touch items-center justify-center gap-2 rounded-md bg-primary-600 px-4 py-3 text-body font-medium text-primary-foreground shadow-sm transition-all duration-normal hover:bg-primary-700 hover:shadow-md focus-visible:outline-none motion-safe:active:scale-[0.98]";

export interface CheckInOutcomePanelProps {
  outcome: CheckInOutcomeCode;
  detailMessage?: string;
  onAction?: () => void;
  onRetry?: () => void;
  className?: string;
}

/** NFR-17 — Campus Pulse signature check-in outcome moment */
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
      role="alert"
      data-testid={`check-in-outcome-${outcome}`}
      data-block-resubmit={outcome === "DuplicateCheckIn" ? "true" : undefined}
      className={cn(
        "outcome-panel-enter flex w-full flex-col gap-6 rounded-lg border p-6 shadow-md",
        washClasses[copy.variant],
        className,
      )}
    >
      <div className="flex flex-col items-center gap-4 text-center sm:flex-row sm:items-start sm:text-left">
        <div
          className={cn(
            "flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-raised shadow-sm",
            iconColorClasses[copy.variant],
          )}
        >
          <Icon className="h-8 w-8" aria-hidden="true" />
        </div>
        <div className="flex-1 space-y-2">
          <h2 className="font-display text-h1 font-semibold text-text-primary">
            {copy.title}
          </h2>
          <p className="text-body text-text-secondary">
            {detailMessage ?? copy.message}
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-3 border-t border-border/60 pt-4">
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
