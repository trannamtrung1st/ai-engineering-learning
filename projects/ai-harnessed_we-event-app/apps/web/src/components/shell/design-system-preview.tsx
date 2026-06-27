"use client";

import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { SkeletonText } from "@/components/ui/skeleton";
import { allDomainStatuses } from "@/lib/status-tokens";

import { LiveQueryStatus } from "./live-query-status";

export function DesignSystemPreview() {
  return (
    <div className="space-y-[var(--gap-section)]">
      <section aria-labelledby="status-tokens-heading" className="space-y-4">
        <h2
          id="status-tokens-heading"
          className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]"
        >
          Domain status tokens
        </h2>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Semantic badges pair icon and text — never color alone.
        </p>
        <div className="flex flex-wrap gap-2">
          {allDomainStatuses.map((status) => (
            <Badge key={status} status={status} />
          ))}
        </div>
      </section>

      <section aria-labelledby="actions-heading" className="space-y-4">
        <h2
          id="actions-heading"
          className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]"
        >
          Actions
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button loading>Loading</Button>
          <Button disabled>Disabled</Button>
        </div>
      </section>

      <section aria-labelledby="alerts-heading" className="space-y-4">
        <h2
          id="alerts-heading"
          className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]"
        >
          Alerts
        </h2>
        <div className="grid gap-3 lg:grid-cols-2">
          <Alert variant="info" title="Information">
            Inline alerts include a reason and next step when something needs attention.
          </Alert>
          <Alert variant="success" title="Success">
            Toasts handle short non-blocking confirmations in feature flows.
          </Alert>
        </div>
      </section>

      <section aria-labelledby="controls-heading" className="space-y-4">
        <h2
          id="controls-heading"
          className="text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]"
        >
          Form controls
        </h2>
        <div className="grid max-w-md gap-4">
          <Input placeholder="Text input" aria-label="Sample text input" />
          <div aria-busy="true" className="space-y-2">
            <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
              Loading skeleton
            </p>
            <SkeletonText lines={3} />
          </div>
        </div>
      </section>

      <section aria-labelledby="live-query-heading">
        <h2
          id="live-query-heading"
          className="mb-4 text-[length:var(--font-size-lg)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]"
        >
          Near-real-time data (NFR-06)
        </h2>
        <LiveQueryStatus />
      </section>
    </div>
  );
}
