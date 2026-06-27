import type { RegistrationState } from "@we-event/domain";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import type { EventSummary, RegistrationStatus } from "@/lib/participant-api";
import { canSelfCheckIn } from "@/lib/participant-rules";

export type CheckInBlockReason =
  | "no-registration"
  | "not-registered-state"
  | "event-not-in-progress"
  | "outside-window"
  | "self-checkin-disabled"
  | "already-checked-in"
  | null;

export interface CheckInPanelState {
  showCheckInButton: boolean;
  alreadyCheckedIn: boolean;
  blockReason: CheckInBlockReason;
}

export interface CheckInPanelViewProps {
  event: EventSummary;
  registration: RegistrationStatus | null;
  panelState: CheckInPanelState;
  submitSuccess?: boolean;
  successTimestamp?: string | null;
  submitError?: string | null;
  submitPending?: boolean;
  onCheckIn?: () => void;
}

export function deriveCheckInPanelState(
  event: EventSummary,
  registration: RegistrationStatus | null,
  now: number = Date.now(),
): CheckInPanelState {
  const selfCheckinEnabled = event.ruleConfig.selfCheckinEnabled ?? true;
  const alreadyCheckedIn =
    registration?.state === "CheckedIn" || registration?.state === "Attended";

  if (alreadyCheckedIn) {
    return {
      showCheckInButton: false,
      alreadyCheckedIn: true,
      blockReason: "already-checked-in",
    };
  }

  if (!registration) {
    return {
      showCheckInButton: false,
      alreadyCheckedIn: false,
      blockReason: "no-registration",
    };
  }

  if (!selfCheckinEnabled) {
    return {
      showCheckInButton: false,
      alreadyCheckedIn: false,
      blockReason: "self-checkin-disabled",
    };
  }

  if (event.state !== "InProgress") {
    return {
      showCheckInButton: false,
      alreadyCheckedIn: false,
      blockReason: "event-not-in-progress",
    };
  }

  if (registration.state !== "Registered") {
    return {
      showCheckInButton: false,
      alreadyCheckedIn: false,
      blockReason: "not-registered-state",
    };
  }

  const checkInAllowed = canSelfCheckIn(
    event.state,
    registration.state,
    event.ruleConfig.checkinOpenAt,
    event.ruleConfig.checkinCloseAt,
    selfCheckinEnabled,
    now,
  );

  if (!checkInAllowed) {
    return {
      showCheckInButton: false,
      alreadyCheckedIn: false,
      blockReason: "outside-window",
    };
  }

  return {
    showCheckInButton: true,
    alreadyCheckedIn: false,
    blockReason: null,
  };
}

function blockReasonAlert(
  reason: CheckInBlockReason,
  event: EventSummary,
  registrationState: RegistrationState | undefined,
): { title: string; message: string } | null {
  switch (reason) {
    case "no-registration":
      return {
        title: "No active registration",
        message: "You must be registered to check in for this event.",
      };
    case "self-checkin-disabled":
      return {
        title: "Self check-in unavailable",
        message: "Self-service check-in is not enabled for this event. Contact the organizer if you need assistance.",
      };
    case "event-not-in-progress":
      return {
        title: "Self check-in unavailable",
        message: "Self check-in is only available while the event is in progress.",
      };
    case "outside-window":
      return {
        title: "Outside check-in window",
        message: `Check-in is not available at this time. The window is ${formatDateTime(event.ruleConfig.checkinOpenAt)} – ${formatDateTime(event.ruleConfig.checkinCloseAt)}.`,
      };
    case "not-registered-state":
      return {
        title: "Check-in not available",
        message: `Only registered participants can check in. Your current status (${registrationState ?? "unknown"}) does not allow self check-in.`,
      };
    case "already-checked-in":
      return null;
    default:
      return null;
  }
}

export function CheckInPanelView({
  event,
  registration,
  panelState,
  submitSuccess = false,
  successTimestamp = null,
  submitError = null,
  submitPending = false,
  onCheckIn,
}: CheckInPanelViewProps) {
  const blockAlert = blockReasonAlert(
    panelState.blockReason,
    event,
    registration?.state,
  );

  return (
    <div className="max-w-xl space-y-6 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
      <div className="space-y-2">
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Check-in window
        </p>
        <p className="text-[length:var(--font-size-sm)] font-[var(--font-weight-medium)]">
          {formatDateTime(event.ruleConfig.checkinOpenAt)} –{" "}
          {formatDateTime(event.ruleConfig.checkinCloseAt)}
        </p>
      </div>

      {registration ? (
        <div className="space-y-2">
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Registration status
          </p>
          <RegistrationStateBadge state={registration.state} />
        </div>
      ) : null}

      {blockAlert ? (
        <Alert variant="warning" title={blockAlert.title}>
          {blockAlert.message}
        </Alert>
      ) : null}

      {submitSuccess && successTimestamp ? (
        <Alert variant="success" title="You are checked in">
          Checked in at {formatDateTime(successTimestamp)}.
        </Alert>
      ) : null}

      {submitError ? (
        <Alert variant="error" title="Check-in blocked">
          {submitError}
        </Alert>
      ) : null}

      {panelState.showCheckInButton && !submitSuccess ? (
        <Button onClick={onCheckIn} loading={submitPending}>
          Check in now
        </Button>
      ) : panelState.alreadyCheckedIn || submitSuccess ? (
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          You are already checked in for this event.
        </p>
      ) : null}
    </div>
  );
}
