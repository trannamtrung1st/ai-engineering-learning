import { Alert } from "@/components/ui/alert";

export interface CapacityMeterProps {
  registered: number;
  capacity: number;
  waitlist: number;
  threshold?: number;
}

export function CapacityMeter({
  registered,
  capacity,
  waitlist,
  threshold = 0.9,
}: CapacityMeterProps) {
  const ratio = capacity > 0 ? registered / capacity : 0;
  const nearingCapacity = ratio >= threshold && ratio < 1;
  const atCapacity = registered >= capacity;

  return (
    <div className="space-y-3 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
            Capacity
          </p>
          <p className="text-[length:var(--font-size-xl)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)]">
            {registered} / {capacity} registered
          </p>
        </div>
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          Waitlist: {waitlist}
        </p>
      </div>

      <div
        className="h-2 overflow-hidden rounded-full bg-[var(--color-bg-subtle)]"
        role="progressbar"
        aria-valuenow={registered}
        aria-valuemin={0}
        aria-valuemax={capacity}
        aria-label={`${registered} of ${capacity} seats filled`}
      >
        <div
          className="h-full rounded-full bg-[var(--color-action-primary-bg)] transition-all"
          style={{ width: `${Math.min(ratio * 100, 100)}%` }}
        />
      </div>

      {atCapacity ? (
        <Alert variant="warning" title="At capacity">
          Registration is full. New sign-ups will join the waitlist when enabled.
        </Alert>
      ) : null}

      {nearingCapacity && !atCapacity ? (
        <Alert variant="warning" title="Nearing capacity">
          {Math.round(ratio * 100)}% of seats are filled. Monitor waitlist promotions.
        </Alert>
      ) : null}
    </div>
  );
}
