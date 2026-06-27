"use client";

import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import {
  EventForm,
  toUpdateEventPayload,
} from "@/components/organizer/event-form";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { fetchOrganizerEvent, updateEvent } from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export default function EditEventPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const router = useRouter();
  const { token, isAdmin } = useOrganizerAuth();
  const queryClient = useQueryClient();

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.detail(eventId),
    queryFn: () => fetchOrganizerEvent(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  if (!isAdmin) {
    return (
      <PageHeader
        title="Edit event"
        subtitle="Only organizer admins can edit event configuration."
      />
    );
  }

  if (eventQuery.isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (eventQuery.isError) {
    return (
      <EmptyFailureBlock
        variant="failure"
        title="Could not load event"
        description={eventQuery.error.message}
        actionLabel="Retry"
        onAction={() => void eventQuery.refetch()}
      />
    );
  }

  const event = eventQuery.data;
  if (!event) {
    return null;
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Edit event"
        subtitle="Update event details and rule configuration. Changes are audited."
      />
      <EventForm
        initial={{
          name: event.name,
          description: event.description,
          location: event.location,
          startAt: event.startAt,
          endAt: event.endAt,
          ruleConfig: event.ruleConfig,
        }}
        eventState={event.state}
        submitLabel="Save changes"
        onSubmit={async (values) => {
          await updateEvent(token!, eventId, toUpdateEventPayload(values));
          await queryClient.invalidateQueries({
            queryKey: queryKeys.organizer.events.detail(eventId),
          });
          await queryClient.invalidateQueries({
            queryKey: queryKeys.organizer.events.listRoot(),
          });
          router.push(`/organizer/events/${eventId}`);
        }}
      />
    </div>
  );
}
