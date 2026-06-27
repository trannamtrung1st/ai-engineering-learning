import type { RegistrationState } from "@we-event/domain";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { registrationStateLabel } from "@/lib/domain-labels";
import { formatDateTime } from "@/lib/format";
import type { EventSummary, RegistrationStatus } from "@/lib/participant-api";
import { canCancelRegistration, canRegister } from "@/lib/participant-rules";

export interface RegistrationStatusPanelViewProps {
  registration: RegistrationStatus | null;
  isLoading?: boolean;
  isError?: boolean;
  error?: Error | null;
  onRetry?: () => void;
  showRegister: boolean;
  showCancel: boolean;
  blockReason: string | null;
  registerPending?: boolean;
  cancelPending?: boolean;
  registerError?: string | null;
  cancelError?: string | null;
  cancelDialogOpen: boolean;
  onCancelDialogOpenChange: (open: boolean) => void;
  onRegister: () => void;
  onConfirmCancel: () => void;
}

function registerBlockReason(event: EventSummary): string | null {
  const { state, ruleConfig } = event;
  if (state !== "RegistrationOpen") {
    return "Registration is not open for this event.";
  }
  if (ruleConfig.registrationPaused) {
    return "Registration is temporarily paused by the organizer.";
  }
  const now = Date.now();
  const open = new Date(ruleConfig.registrationOpenAt).getTime();
  const close = new Date(ruleConfig.registrationCloseAt).getTime();
  if (now < open) {
    return `Registration opens ${formatDateTime(ruleConfig.registrationOpenAt)}.`;
  }
  if (now > close) {
    return "The registration window has closed.";
  }
  return null;
}

export function waitlistPromotionCopy(): string {
  return "You will be registered automatically when a seat opens. Promotion follows FIFO queue order.";
}

export function deriveRegistrationPanelState(
  event: EventSummary,
  registration: RegistrationStatus | null,
): Pick<RegistrationStatusPanelViewProps, "showRegister" | "showCancel" | "blockReason"> {
  const showRegister =
    !registration &&
    canRegister(
      event.state,
      event.ruleConfig.registrationPaused,
      event.ruleConfig.registrationOpenAt,
      event.ruleConfig.registrationCloseAt,
      null,
    );
  const showCancel = Boolean(
    registration &&
      canCancelRegistration(registration.state, event.ruleConfig.registrationCloseAt),
  );
  const blockReason = !registration && !showRegister ? registerBlockReason(event) : null;
  return { showRegister, showCancel, blockReason };
}

/** Traceability: AC-01, AC-02, AC-03, FR-10, FR-11, FR-12 */
export function RegistrationStatusPanelView({
  registration,
  isLoading = false,
  isError = false,
  error = null,
  onRetry,
  showRegister,
  showCancel,
  blockReason,
  registerPending = false,
  cancelPending = false,
  registerError = null,
  cancelError = null,
  cancelDialogOpen,
  onCancelDialogOpenChange,
  onRegister,
  onConfirmCancel,
}: RegistrationStatusPanelViewProps) {
  const registrationLabel = registration ? registrationStateLabel(registration.state) : null;

  if (isLoading) {
    return <Skeleton className="h-32 w-full" data-testid="registration-panel-loading" />;
  }

  if (isError) {
    return (
      <EmptyFailureBlock
        variant="failure"
        title="Could not load registration status"
        description={error?.message ?? "Try again."}
        actionLabel="Retry"
        onAction={onRetry}
      />
    );
  }

  return (
    <div className="space-y-4" data-testid="registration-status-panel">
      {registration ? (
        <div className="space-y-3">
          <RegistrationStateBadge state={registration.state} />
          {registrationLabel?.hint ? (
            <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              {registrationLabel.hint}
            </p>
          ) : null}
          {registration.state === "Waitlisted" && registration.waitlistPosition ? (
            <>
              <p className="text-[length:var(--font-size-sm)] font-[var(--font-weight-medium)] text-[var(--color-text-primary)]">
                Queue position: {registration.waitlistPosition}
              </p>
              <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
                {waitlistPromotionCopy()}
              </p>
            </>
          ) : null}
          {registration.reasonText ? (
            <Alert variant="warning" title="Status note">
              {registration.reasonText}
            </Alert>
          ) : null}
          <dl className="space-y-1 text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
            <div className="flex flex-wrap gap-x-2">
              <dt>Requested</dt>
              <dd>{formatDateTime(registration.requestedAt)}</dd>
            </div>
            <div className="flex flex-wrap gap-x-2">
              <dt>Last updated</dt>
              <dd>{formatDateTime(registration.updatedAt)}</dd>
            </div>
          </dl>
        </div>
      ) : (
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          You have not registered for this event yet.
        </p>
      )}

      {blockReason ? (
        <Alert variant="info" title="Registration unavailable">
          {blockReason}
        </Alert>
      ) : null}

      {registerError ? (
        <Alert variant="error" title="Registration blocked">
          {registerError}
        </Alert>
      ) : null}

      {cancelError ? (
        <Alert variant="error" title="Cancellation blocked">
          {cancelError}
        </Alert>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {showRegister ? (
          <Button
            onClick={onRegister}
            loading={registerPending}
            aria-label="Register for this event"
          >
            Register
          </Button>
        ) : null}

        {showCancel ? (
          <Button
            variant="danger"
            onClick={() => onCancelDialogOpenChange(true)}
            disabled={cancelPending}
            aria-label="Cancel registration"
          >
            Cancel registration
          </Button>
        ) : null}
      </div>

      <Dialog open={cancelDialogOpen} onOpenChange={onCancelDialogOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel registration?</DialogTitle>
            <DialogDescription>
              {registration?.state === "Registered"
                ? "Your seat will be released. If a waitlist is active, the next participant in queue may be promoted automatically."
                : "Your waitlist entry will be removed. This does not release a seat or promote other waitlisted participants."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="secondary" onClick={() => onCancelDialogOpenChange(false)}>
              Keep registration
            </Button>
            <Button variant="danger" loading={cancelPending} onClick={onConfirmCancel}>
              Confirm cancellation
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export function registrationStateAllowsCancel(state: RegistrationState): boolean {
  return state === "Registered" || state === "Waitlisted";
}
