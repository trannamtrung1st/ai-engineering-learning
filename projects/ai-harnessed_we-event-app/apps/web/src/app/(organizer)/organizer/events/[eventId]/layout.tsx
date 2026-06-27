"use client";

import { useParams } from "next/navigation";

import { EventWorkspaceNav } from "@/components/organizer/event-workspace-nav";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { canAccessEvent } from "@/lib/organizer-rules";
import { fetchOrganizerEvent } from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export default function EventWorkspaceLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token, session } = useOrganizerAuth();

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.detail(eventId),
    queryFn: () => fetchOrganizerEvent(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  if (eventQuery.isLoading) {
    return <Skeleton className="h-12 w-full" />;
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

  if (session && !canAccessEvent(session, eventId)) {
    return (
      <EmptyFailureBlock
        variant="failure"
        title="Access denied"
        description="You are not assigned to this event."
      />
    );
  }

  return (
    <div className="space-y-6">
      <EventWorkspaceNav eventId={eventId} />
      {children}
    </div>
  );
}
