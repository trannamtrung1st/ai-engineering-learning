"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import {
  CheckInPanelView,
  deriveCheckInPanelState,
} from "@/components/participant/check-in-panel-view";
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
  selfCheckin,
} from "@/lib/participant-api";
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
  const panelState = event ? deriveCheckInPanelState(event, registration) : null;

  const submitError =
    checkinMutation.error instanceof ApiClientError
      ? checkinMutation.error.message
      : checkinMutation.error instanceof Error
        ? checkinMutation.error.message
        : null;

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

      {event && panelState && registrationQuery.isSuccess ? (
        <CheckInPanelView
          event={event}
          registration={registration}
          panelState={panelState}
          submitSuccess={checkinMutation.isSuccess}
          successTimestamp={checkinMutation.data?.checkinAt ?? null}
          submitError={submitError}
          submitPending={checkinMutation.isPending}
          onCheckIn={() => checkinMutation.mutate()}
        />
      ) : null}
    </div>
  );
}
