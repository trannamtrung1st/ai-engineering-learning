"use client";

import { useLiveQuery } from "@/hooks/use-live-query";
import { fetchHealth } from "@/lib/api-client";
import { LIVE_REFRESH_INTERVALS } from "@/lib/query-config";
import { queryKeys } from "@/lib/query-keys";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/**
 * Demonstrates NFR-06 near-real-time polling via shared useLiveQuery infrastructure.
 * Not an organizer operations dashboard — that ships in web-organizer-journeys.
 */
export function LiveQueryStatus() {
  const { data, error, isPending, isError, isFetching, refetch } = useLiveQuery({
    queryKey: queryKeys.health,
    queryFn: fetchHealth,
    mode: "organizerDashboard",
  });

  if (isPending) {
    return (
      <div aria-busy="true" className="space-y-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-16 w-full rounded-[var(--radius-md)]" />
      </div>
    );
  }

  if (isError) {
    return (
      <Alert variant="error" title="API connection unavailable">
        {error.message}
        <div className="mt-3">
          <Button size="sm" variant="secondary" onClick={() => refetch()}>
            Retry
          </Button>
        </div>
      </Alert>
    );
  }

  const healthy = data.status === "ok" && data.db === "connected";

  return (
    <div className="space-y-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[length:var(--font-size-sm)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
          Live query readiness
        </h3>
        <Badge status={healthy ? "registered" : "waitlisted"}>
          {healthy ? "Connected" : "Degraded"}
        </Badge>
        {isFetching ? (
          <span className="text-[length:var(--font-size-xs)] text-[var(--color-text-secondary)]">
            Refreshing…
          </span>
        ) : null}
      </div>
      <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
        Polls{" "}
        <code className="font-mono text-[length:var(--font-size-xs)]">/api/v1/health</code> via
        same-origin Next.js proxy every {LIVE_REFRESH_INTERVALS.organizerDashboard / 1000}s using
        TanStack Query — the same policy organizer dashboards will use in the next slice.
      </p>
      <dl className="grid gap-2 text-[length:var(--font-size-sm)] sm:grid-cols-3">
        <div>
          <dt className="text-[var(--color-text-secondary)]">API</dt>
          <dd className="font-[var(--font-weight-medium)]">{data.status}</dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-secondary)]">Database</dt>
          <dd className="font-[var(--font-weight-medium)]">{data.db}</dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-secondary)]">Request id</dt>
          <dd className="truncate font-mono text-[length:var(--font-size-xs)]">{data.requestId}</dd>
        </div>
      </dl>
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {healthy ? "API health check connected." : "API health check degraded."}
      </div>
    </div>
  );
}
