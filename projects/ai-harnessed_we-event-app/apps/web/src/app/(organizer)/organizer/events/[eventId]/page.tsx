"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { EventCoverMedia } from "@/components/participant/event-cover-media";
import { EventStateBadge } from "@/components/participant/event-state-badge";
import { CapacityMeter } from "@/components/organizer/capacity-meter";
import { EventDashboardSkeleton } from "@/components/organizer/event-dashboard-skeleton";
import { EventLifecycleActions } from "@/components/organizer/event-lifecycle-actions";
import { FeedbackCompletionTracker } from "@/components/organizer/feedback-completion-tracker";
import { KpiSummaryStrip } from "@/components/layout/kpi-summary-strip";
import { EmptyFailureBlock } from "@/components/layout/empty-failure-block";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useLiveQuery } from "@/hooks/use-live-query";
import { ApiClientError } from "@/lib/api-client";
import { buildEventDashboardKpiItems } from "@/lib/event-dashboard-kpis";
import { formatDateTime } from "@/lib/format";
import {
  countRegisteredSeats,
  downloadEligibilityExport,
  fetchEventDashboardMetrics,
  fetchOrganizerEvent,
} from "@/lib/organizer-api";
import { queryKeys } from "@/lib/query-keys";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export default function EventDashboardPage() {
  const params = useParams<{ eventId: string }>();
  const eventId = params.eventId;
  const { token, isAdmin } = useOrganizerAuth();
  const { push } = useToast();
  const [exporting, setExporting] = useState(false);

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

  const basePath = `/organizer/events/${eventId}`;
  const kpiLinks = {
    registrations: `${basePath}/registrations`,
    waitlist: `${basePath}/waitlist`,
    checkIn: `${basePath}/check-in`,
    eligibility: `${basePath}/eligibility`,
  };

  async function handleExport() {
    if (!token) {
      return;
    }

    setExporting(true);
    try {
      const result = await downloadEligibilityExport(token, eventId);
      push({
        title: "Export downloaded",
        description: `${result.filename} (${result.rowCount} rows)`,
        variant: "success",
      });
    } catch (error) {
      push({
        title: "Export failed",
        description:
          error instanceof ApiClientError ? error.message : "Try again.",
        variant: "error",
      });
    } finally {
      setExporting(false);
    }
  }

  if (eventQuery.isLoading || metricsQuery.isLoading) {
    return <EventDashboardSkeleton />;
  }

  if (eventQuery.isLoadingError || metricsQuery.isLoadingError) {
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

  const metricsHasStaleData = Boolean(metrics);
  const metricsPollFailed =
    metricsQuery.isRefetchError ||
    (metricsQuery.isError && metricsHasStaleData);
  const metricsRefreshError = metricsPollFailed
    ? (metricsQuery.failureReason?.message ??
      metricsQuery.error?.message ??
      "Dashboard metrics could not be refreshed.")
    : undefined;

  const capacity = countRegisteredSeats(
    event.ruleConfig,
    metrics.registeredSeats,
    metrics.waitlist,
  );

  const kpiItems = buildEventDashboardKpiItems(metrics, kpiLinks);

  return (
    <div className="space-y-8">
      <PageHeader
        title={event.name}
        subtitle={`${formatDateTime(event.startAt)} · ${event.location || "Location TBD"}`}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <EventStateBadge state={event.state} />
            {isAdmin ? (
              <Button
                size="sm"
                variant="secondary"
                disabled={exporting}
                onClick={() => void handleExport()}
              >
                {exporting ? "Exporting…" : "Export operational data"}
              </Button>
            ) : null}
          </div>
        }
      />

      <EventCoverMedia
        coverImageUrl={event.coverImageUrl}
        alt={`Cover image for ${event.name}`}
        variant="hero"
      />

      {isAdmin ? <EventLifecycleActions event={event} /> : null}

      <CapacityMeter
        registered={capacity.registered}
        capacity={capacity.capacity}
        waitlist={capacity.waitlist}
      />

      <KpiSummaryStrip
        isRefreshing={metricsQuery.isFetching && !metricsQuery.isLoading}
        refreshError={metricsRefreshError}
        onRetryRefresh={
          metricsPollFailed
            ? () => {
                void metricsQuery.refetch();
              }
            : undefined
        }
        items={kpiItems}
      />

      <FeedbackCompletionTracker
        metrics={metrics}
        links={{ registrations: kpiLinks.registrations }}
      />

      <section className="space-y-3">
        <h2 className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)]">
          Drill-down
        </h2>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Open operational tables for registrations (including status history),
          waitlist FIFO queue, check-in console, and eligibility review.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button asChild size="sm" variant="secondary">
            <Link href={kpiLinks.registrations}>Registrations</Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={kpiLinks.waitlist}>Waitlist</Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={kpiLinks.checkIn}>Check-in console</Link>
          </Button>
          <Button asChild size="sm" variant="secondary">
            <Link href={kpiLinks.eligibility}>Eligibility</Link>
          </Button>
          {isAdmin ? (
            <>
              <Button asChild size="sm" variant="ghost">
                <Link href={`/organizer/audit?eventId=${eventId}`}>Audit log</Link>
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={exporting}
                onClick={() => void handleExport()}
              >
                Export CSV
              </Button>
            </>
          ) : null}
        </div>
      </section>
    </div>
  );
}
