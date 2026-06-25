"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Form, FormField } from "@/components/ui/form";
import { NumberInput } from "@/components/ui/field";
import { Textarea } from "@/components/ui/textarea";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import {
  fetchEvent,
  fetchRegistrationStatus,
  submitFeedback,
} from "@/lib/participant-api";
import { canSubmitFeedback } from "@/lib/participant-rules";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

const feedbackFormSchema = z.object({
  overallRating: z.coerce
    .number({ invalid_type_error: "Rating must be a number." })
    .int("Rating must be a whole number.")
    .min(1, "Rating must be at least 1.")
    .max(5, "Rating must be at most 5."),
  comments: z
    .string()
    .max(4000, "Comments must be 4000 characters or fewer.")
    .optional(),
});

type FeedbackFormValues = z.infer<typeof feedbackFormSchema>;

export default function FeedbackPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const { push } = useToast();

  const form = useForm<FeedbackFormValues>({
    defaultValues: {
      overallRating: 4,
      comments: "",
    },
    mode: "onBlur",
  });

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.events.detail(eventId),
    queryFn: () => fetchEvent(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const registrationQuery = useLiveQuery({
    queryKey: queryKeys.registrations.status(eventId),
    queryFn: () => fetchRegistrationStatus(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const feedbackMutation = useMutation({
    mutationFn: (values: FeedbackFormValues) =>
      submitFeedback(token!, eventId, {
        registrationId: registrationQuery.data?.registration?.registrationId,
        answers: {
          overallRating: values.overallRating,
          ...(values.comments?.trim() ? { comments: values.comments.trim() } : {}),
        },
      }),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.registrations.status(eventId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.registrations.mineAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.events.listRoot() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.eligibility.me(eventId) });
      push({
        title: "Feedback submitted",
        description: `Submitted at ${formatDateTime(result.submittedAt)}`,
        variant: "success",
      });
    },
    onError: (error) => {
      push({
        title: "Submission failed",
        description: error instanceof Error ? error.message : "Try again.",
        variant: "error",
      });
    },
  });

  const event = eventQuery.data;
  const registration = registrationQuery.data?.registration ?? null;
  const feedbackAllowed = event
    ? canSubmitFeedback(
        event.state,
        registration?.state,
        event.ruleConfig.feedbackOpenAt,
        event.ruleConfig.feedbackCloseAt,
      )
    : false;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Submit feedback"
        subtitle={
          event
            ? `Share your experience for ${event.name}.`
            : "Post-event feedback form."
        }
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link href={`/events/${eventId}`}>Back to event</Link>
          </Button>
        }
      />

      {eventQuery.isLoading || registrationQuery.isLoading ? (
        <Skeleton className="h-64 w-full max-w-xl" />
      ) : null}

      {eventQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load event"
          description={eventQuery.error.message}
          actionLabel="Retry"
          onAction={() => void eventQuery.refetch()}
        />
      ) : null}

      {registrationQuery.isError ? (
        <EmptyFailureBlock
          variant="failure"
          title="Could not load registration status"
          description={registrationQuery.error.message}
          actionLabel="Retry"
          onAction={() => void registrationQuery.refetch()}
        />
      ) : null}

      {feedbackMutation.isSuccess ? (
        <Alert variant="success" title="Thank you for your feedback">
          Your response was recorded at{" "}
          {formatDateTime(feedbackMutation.data.submittedAt)}.
          <div className="mt-4">
            <Button asChild variant="secondary" size="sm">
              <Link href={`/events/${eventId}/eligibility`}>View eligibility</Link>
            </Button>
          </div>
        </Alert>
      ) : null}

      {event && registrationQuery.isSuccess && !feedbackMutation.isSuccess ? (
        <Form
          form={form}
          className="max-w-xl space-y-6 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6"
          onSubmit={(values) => {
            const parsed = feedbackFormSchema.safeParse(values);
            if (!parsed.success) {
              for (const issue of parsed.error.issues) {
                const field = issue.path[0];
                if (typeof field === "string") {
                  form.setError(field as keyof FeedbackFormValues, {
                    message: issue.message,
                  });
                }
              }
              return;
            }
            feedbackMutation.mutate(parsed.data);
          }}
        >
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Feedback window: {formatDateTime(event.ruleConfig.feedbackOpenAt)} –{" "}
            {formatDateTime(event.ruleConfig.feedbackCloseAt)}
          </p>

          {registration?.state !== "Attended" ? (
            <Alert variant="warning" title="Feedback not available">
              Only attended participants can submit feedback after the event is completed.
            </Alert>
          ) : null}

          {registration?.state === "Attended" && event.state !== "Completed" ? (
            <Alert variant="warning" title="Feedback not open yet">
              Feedback is only available after the event is completed.
            </Alert>
          ) : null}

          {registration?.state === "Attended" &&
          event.state === "Completed" &&
          !feedbackAllowed ? (
            <Alert variant="warning" title="Outside feedback window">
              Feedback is not available at this time. Submit during the configured window
              above.
            </Alert>
          ) : null}

          {feedbackMutation.isError ? (
            <Alert variant="error" title="Submission blocked">
              {feedbackMutation.error instanceof ApiClientError
                ? feedbackMutation.error.message
                : "Unable to submit feedback."}
            </Alert>
          ) : null}

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

          <Button type="submit" loading={feedbackMutation.isPending} disabled={!feedbackAllowed}>
            Submit feedback
          </Button>
        </Form>
      ) : null}
    </div>
  );
}
