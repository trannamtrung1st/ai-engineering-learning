"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { RegistrationStateBadge } from "@/components/participant/registration-state-badge";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import {
  fetchEvent,
  fetchRegistrationStatus,
  selfCheckin,
} from "@/lib/participant-api";
import { canSelfCheckIn } from "@/lib/participant-rules";
import { queryKeys } from "@/lib/query-keys";
import { useAuth } from "@/providers/auth-provider";

export default function CheckInPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token } = useAuth();
  const queryClient = useQueryClient();
  const { push } = useToast();

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.events.detail(eventId),
    queryFn: () => fetchEvent(token!, eventId),
    mode: "checkInConsole",
    enabled: Boolean(token),
  });

  const registrationQuery = useLiveQuery({
    queryKey: queryKeys.registrations.status(eventId),
    queryFn: () => fetchRegistrationStatus(token!, eventId),
    mode: "checkInConsole",
    enabled: Boolean(token),
  });

  const checkinMutation = useMutation({
    mutationFn: () => selfCheckin(token!, eventId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.registrations.status(eventId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.registrations.mineAll() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.events.listRoot() });
      push({
        title: "Check-in successful",
        description: `Checked in at ${formatDateTime(result.checkinAt)}`,
        variant: "success",
      });
    },
    onError: (error) => {
      push({
        title: "Check-in failed",
        description: error instanceof Error ? error.message : "Try again.",
        variant: "error",
      });
    },
  });

  const event = eventQuery.data;
  const registration = registrationQuery.data?.registration ?? null;
  const alreadyCheckedIn =
    registration?.state === "CheckedIn" || registration?.state === "Attended";
  const checkInAllowed = event
    ? canSelfCheckIn(
        event.state,
        registration?.state,
        event.ruleConfig.checkinOpenAt,
        event.ruleConfig.checkinCloseAt,
      )
    : false;

  return (
    <div className="space-y-8">
      <PageHeader
        title="Self check-in"
        subtitle={
          event
            ? `Check in for ${event.name} during the configured check-in window.`
            : "Confirm your attendance for this event."
        }
        actions={
          <Button asChild variant="ghost" size="sm">
            <Link href={`/events/${eventId}`}>Back to event</Link>
          </Button>
        }
      />

      {eventQuery.isLoading || registrationQuery.isLoading ? (
        <Skeleton className="h-48 w-full max-w-xl" />
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

      {event && registrationQuery.isSuccess ? (
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
          ) : (
            <Alert variant="warning" title="No active registration">
              You must be registered to check in for this event.
            </Alert>
          )}

          {registration && event.state !== "InProgress" ? (
            <Alert variant="warning" title="Self check-in unavailable">
              Self check-in is only available while the event is in progress.
            </Alert>
          ) : null}

          {registration?.state === "Registered" && event.state === "InProgress" && !checkInAllowed ? (
            <Alert variant="warning" title="Outside check-in window">
              Check-in is not available at this time. The window is{" "}
              {formatDateTime(event.ruleConfig.checkinOpenAt)} –{" "}
              {formatDateTime(event.ruleConfig.checkinCloseAt)}.
            </Alert>
          ) : null}

          {registration && registration.state !== "Registered" && !alreadyCheckedIn ? (
            <Alert variant="warning" title="Check-in not available">
              Only registered participants can check in. Your current status does not allow
              self check-in.
            </Alert>
          ) : null}

          {checkinMutation.isSuccess ? (
            <Alert variant="success" title="You are checked in">
              Checked in at {formatDateTime(checkinMutation.data.checkinAt)}.
            </Alert>
          ) : null}

          {checkinMutation.isError ? (
            <Alert variant="error" title="Check-in blocked">
              {checkinMutation.error instanceof ApiClientError
                ? checkinMutation.error.message
                : "Unable to complete check-in. Try again."}
            </Alert>
          ) : null}

          {checkInAllowed && !alreadyCheckedIn && !checkinMutation.isSuccess ? (
            <Button
              onClick={() => checkinMutation.mutate()}
              loading={checkinMutation.isPending}
            >
              Check in now
            </Button>
          ) : alreadyCheckedIn || checkinMutation.isSuccess ? (
            <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              You are already checked in for this event.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
