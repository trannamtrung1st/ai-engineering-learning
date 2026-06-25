"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { EventStateBadge } from "@/components/participant/event-state-badge";
import { CapacityMeter } from "@/components/organizer/capacity-meter";
import { EventLifecycleActions } from "@/components/organizer/event-lifecycle-actions";
import { KpiSummaryStrip } from "@/components/layout/kpi-summary-strip";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useLiveQuery } from "@/hooks/use-live-query";
import { formatDateTime } from "@/lib/format";
import {
  countRegisteredSeats,
  fetchEventDashboardMetrics,
  fetchOrganizerEvent,
} from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export default function EventDashboardPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token, isAdmin } = useOrganizerAuth();

  const eventQuery = useLiveQuery({
    queryKey: queryKeys.organizer.events.detail(eventId),
    queryFn: () => fetchOrganizerEvent(token!, eventId),
    mode: "eventList",
    enabled: Boolean(token),
  });

  const metricsQuery = useLiveQuery({
    queryKey: queryKeys.organizer.dashboard(eventId),
    queryFn: () => fetchEventDashboardMetrics(token!, eventId),
    mode: "organizerDashboard",
    enabled: Boolean(token),
  });

  const event = eventQuery.data;
  const metrics = metricsQuery.data;

  if (eventQuery.isLoading || metricsQuery.isLoading) {
    return <Skeleton className="h-64 w-full" />;
  }

  if (eventQuery.isError || metricsQuery.isError) {
    return (
      <EmptyFailureBlock
        variant="failure"
        title="Could not load dashboard"
        description={
          eventQuery.error?.message ?? metricsQuery.error?.message ?? "Try again."
        }
        actionLabel="Retry"
        onAction={() => {
          void eventQuery.refetch();
          void metricsQuery.refetch();
        }}
      />
    );
  }

  if (!event || !metrics) {
    return null;
  }

  const capacity = countRegisteredSeats(
    event.ruleConfig,
    metrics.registeredSeats,
    metrics.waitlist,
  );

  return (
    <div className="space-y-8">
      <PageHeader
        title={event.name}
        subtitle={`${formatDateTime(event.startAt)} · ${event.location || "Location TBD"}`}
        actions={<EventStateBadge state={event.state} />}
      />

      {isAdmin ? <EventLifecycleActions event={event} /> : null}

      <CapacityMeter
        registered={capacity.registered}
        capacity={capacity.capacity}
        waitlist={capacity.waitlist}
      />

      <KpiSummaryStrip
        items={[
          {
            label: "Registrations",
            value: metrics.registrations,
            hint: "All registration records",
          },
          {
            label: "Waitlist",
            value: metrics.waitlist,
            hint: "FIFO queue position preserved",
          },
          {
            label: "Check-ins",
            value: metrics.checkedIn + metrics.attended,
            hint: "Checked in or attended",
          },
          {
            label: "Eligibility",
            value: `${metrics.eligible} eligible`,
            hint: `${metrics.notEligible} not eligible · ${metrics.pendingEligibility} pending`,
          },
        ]}
      />

      <section className="space-y-3">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Drill-down
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="secondary">
            <Link href={`/organizer/events/${eventId}/registrations`}>
              Registrations
            </Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={`/organizer/events/${eventId}/waitlist`}>Waitlist</Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={`/organizer/events/${eventId}/check-in`}>Check-in console</Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={`/organizer/events/${eventId}/eligibility`}>Eligibility</Link>
          </Button>
          {isAdmin ? (
            <Button asChild size="sm" variant="ghost">
              <Link href={`/organizer/audit?eventId=${eventId}`}>Audit log</Link>
            </Button>
          ) : null}
        </div>
      </section>
    </div>
  );
}
