"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import {
  deriveFeedbackPanelState,
  FeedbackPanelView,
  type FeedbackFormValues,
} from "@/components/participant/feedback-panel-view";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
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
  const panelState = event ? deriveFeedbackPanelState(event, registration) : null;

  const submitError =
    feedbackMutation.error instanceof ApiClientError
      ? feedbackMutation.error.message
      : feedbackMutation.error instanceof Error
        ? feedbackMutation.error.message
        : null;

  const handleSubmit = () => {
    const values = form.getValues();
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
  };

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
        <div className="max-w-xl space-y-4">
          <FeedbackPanelView
            event={event!}
            registration={registration}
            panelState={panelState!}
            form={form}
            submitSuccess
            successTimestamp={feedbackMutation.data.submittedAt}
          />
          <Button asChild variant="secondary" size="sm">
            <Link href={`/events/${eventId}/eligibility`}>View eligibility</Link>
          </Button>
        </div>
      ) : null}

      {event && panelState && registrationQuery.isSuccess && !feedbackMutation.isSuccess ? (
        <FeedbackPanelView
          event={event}
          registration={registration}
          panelState={panelState}
          form={form}
          submitError={submitError}
          submitPending={feedbackMutation.isPending}
          onSubmit={handleSubmit}
        />
      ) : null}
    </div>
  );
}
