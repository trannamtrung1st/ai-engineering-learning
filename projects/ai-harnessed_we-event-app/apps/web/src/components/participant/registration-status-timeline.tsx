import type { RegistrationState } from "@we-event/domain";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { Alert } from "@/components/ui/alert";
import { registrationStateLabel } from "@/lib/domain-labels";
import { formatDateTime } from "@/lib/format";

export interface RegistrationStatusTimelineProps {
  state: RegistrationState;
  updatedAt: string;
  waitlistPosition?: number | null;
  reasonText?: string | null;
}

/** Traceability: FR-29 — status badge, timeline timestamps, waitlist position, reason text */
export function RegistrationStatusTimeline({
  state,
  updatedAt,
  waitlistPosition,
  reasonText,
}: RegistrationStatusTimelineProps) {
  const statusLabel = registrationStateLabel(state);

  return (
    <div className="space-y-3" data-testid="registration-status-timeline">
      <RegistrationStateBadge state={state} />
      {statusLabel.hint ? (
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          {statusLabel.hint}
        </p>
      ) : null}
      {state === "Waitlisted" && waitlistPosition ? (
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Queue position: {waitlistPosition}
        </p>
      ) : null}
      {reasonText ? (
        <Alert variant="warning" title="Status note">
          {reasonText}
        </Alert>
      ) : null}
      <dl className="grid gap-1 text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
        <div className="flex flex-wrap gap-x-2">
          <dt className="font-[var(--font-weight-medium)]">Current status</dt>
          <dd>{statusLabel.label}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="font-[var(--font-weight-medium)]">Last updated</dt>
          <dd>{formatDateTime(updatedAt)}</dd>
        </div>
      </dl>
    </div>
  );
}
