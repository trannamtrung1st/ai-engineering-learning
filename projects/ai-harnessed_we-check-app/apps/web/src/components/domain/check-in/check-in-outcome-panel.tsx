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
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import {
  type CheckInOutcomeCode,
  checkInOutcomeMessages,
} from "@/lib/copy/checkin-messages";
import { cn } from "@/lib/cn";

const outcomeIcons: Record<CheckInOutcomeCode, LucideIcon> = {
  Present: CheckCircle2,
  ExpiredQr: Clock,
  OutOfRadius: MapPinOff,
  GpsDisabled: LocateOff,
  DuplicateCheckIn: Info,
  SpoofSuspected: ShieldAlert,
  SessionNotActive: CalendarX,
  NotEnrolled: UserX,
  NetworkError: WifiOff,
};

export interface CheckInOutcomePanelProps {
  outcome: CheckInOutcomeCode;
  onAction?: () => void;
  className?: string;
}

/** NFR-17 — check-in outcome panel with Vietnamese messages per ui-states §4.3 */
export function CheckInOutcomePanel({
  outcome,
  onAction,
  className,
}: CheckInOutcomePanelProps) {
  const copy = checkInOutcomeMessages[outcome];
  const Icon = outcomeIcons[outcome];

  return (
    <div
      data-testid={`check-in-outcome-${outcome}`}
      className={cn("flex flex-col gap-4", className)}
    >
      <Alert variant={copy.variant} icon={Icon} title={copy.title}>
        {copy.message}
      </Alert>
      <Button type="button" onClick={onAction} className="w-full">
        {copy.cta}
      </Button>
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
