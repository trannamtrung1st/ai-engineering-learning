import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FormField } from "@/components/ui/form";
import { NumberInput } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { formatDateTime } from "@/lib/format";
import type { EventSummary, RegistrationStatus } from "@/lib/participant-api";
import { canSubmitFeedback } from "@/lib/participant-rules";
import type { UseFormReturn } from "react-hook-form";

export type FeedbackBlockReason =
  | "not-attended"
  | "event-not-completed"
  | "outside-window"
  | null;

export interface FeedbackPanelState {
  canSubmit: boolean;
  blockReason: FeedbackBlockReason;
}

export interface FeedbackFormValues {
  overallRating: number;
  comments?: string;
}

export interface FeedbackPanelViewProps {
  event: EventSummary;
  registration: RegistrationStatus | null;
  panelState: FeedbackPanelState;
  form: UseFormReturn<FeedbackFormValues>;
  submitSuccess?: boolean;
  successTimestamp?: string | null;
  submitError?: string | null;
  submitPending?: boolean;
  onSubmit?: () => void;
}

export function deriveFeedbackPanelState(
  event: EventSummary,
  registration: RegistrationStatus | null,
  now: number = Date.now(),
): FeedbackPanelState {
  if (!registration || registration.state !== "Attended") {
    return { canSubmit: false, blockReason: "not-attended" };
  }

  if (event.state !== "Completed") {
    return { canSubmit: false, blockReason: "event-not-completed" };
  }

  const canSubmit = canSubmitFeedback(
    event.state,
    registration.state,
    event.ruleConfig.feedbackOpenAt,
    event.ruleConfig.feedbackCloseAt,
    now,
  );

  if (!canSubmit) {
    return { canSubmit: false, blockReason: "outside-window" };
  }

  return { canSubmit: true, blockReason: null };
}

function blockReasonAlert(
  reason: FeedbackBlockReason,
  event: EventSummary,
): { title: string; message: string } | null {
  switch (reason) {
    case "not-attended":
      return {
        title: "Feedback not available",
        message: "Only attended participants can submit feedback after the event is completed.",
      };
    case "event-not-completed":
      return {
        title: "Feedback not open yet",
        message: "Feedback is only available after the event is completed.",
      };
    case "outside-window":
      return {
        title: "Outside feedback window",
        message: `Feedback is not available at this time. Submit during the configured window (${formatDateTime(event.ruleConfig.feedbackOpenAt)} – ${formatDateTime(event.ruleConfig.feedbackCloseAt)}).`,
      };
    default:
      return null;
  }
}

export function FeedbackPanelView({
  event,
  registration,
  panelState,
  form,
  submitSuccess = false,
  successTimestamp = null,
  submitError = null,
  submitPending = false,
  onSubmit,
}: FeedbackPanelViewProps) {
  const blockAlert = blockReasonAlert(panelState.blockReason, event);

  return (
    <div className="max-w-xl space-y-6 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
      <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
        Feedback window: {formatDateTime(event.ruleConfig.feedbackOpenAt)} –{" "}
        {formatDateTime(event.ruleConfig.feedbackCloseAt)}
      </p>

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
        <Alert variant="success" title="Thank you for your feedback">
          Your response was recorded at {formatDateTime(successTimestamp)}.
        </Alert>
      ) : null}

      {submitError ? (
        <Alert variant="error" title="Submission blocked">
          {submitError}
        </Alert>
      ) : null}

      {!submitSuccess ? (
        <>
          <FormField
            name="overallRating"
            control={form.control}
            label="Overall rating"
            required
            render={({ field }) => (
              <NumberInput
                id="overall-rating"
                min={1}
                max={5}
                value={field.value}
                onChange={(changeEvent) => field.onChange(Number(changeEvent.target.value))}
                onBlur={field.onBlur}
                name={field.name}
                ref={field.ref}
                error={Boolean(form.formState.errors.overallRating)}
              />
            )}
          />

          <FormField
            name="comments"
            control={form.control}
            label="Comments"
            helperText="Optional — share highlights or suggestions."
            render={({ field }) => (
              <Textarea
                id="feedback-comments"
                rows={5}
                value={field.value ?? ""}
                onChange={field.onChange}
                onBlur={field.onBlur}
                name={field.name}
                ref={field.ref}
              />
            )}
          />

          <Button
            type="button"
            onClick={onSubmit}
            loading={submitPending}
            disabled={!panelState.canSubmit}
          >
            Submit feedback
          </Button>
        </>
      ) : null}
    </div>
  );
}
