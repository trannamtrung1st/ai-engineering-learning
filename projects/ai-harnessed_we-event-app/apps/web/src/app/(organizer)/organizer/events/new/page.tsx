"use client";

import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { PageHeader } from "@/components/layout/page-header";
import {
  EventForm,
  toCreateEventPayload,
} from "@/components/organizer/event-form";
import { createEvent } from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export default function CreateEventPage() {
  const router = useRouter();
  const { token, isAdmin } = useOrganizerAuth();
  const queryClient = useQueryClient();

  if (!isAdmin) {
    return (
      <PageHeader
        title="Create event"
        subtitle="Only organizer admins can create events."
      />
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Create event"
        subtitle="Configure event details, capacity, windows, and feedback rules."
      />
      <EventForm
        submitLabel="Create event"
        onSubmit={async (values) => {
          const created = await createEvent(token!, toCreateEventPayload(values));
          await queryClient.invalidateQueries({
            queryKey: queryKeys.organizer.events.listRoot(),
          });
          router.push(`/organizer/events/${created.eventId}`);
        }}
      />
    </div>
  );
}
