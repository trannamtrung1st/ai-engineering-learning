import { Skeleton } from "@/components/ui/skeleton";

/** Layout-preserving loading placeholders for organizer event dashboard (TC-FR-22-010). */
export function EventDashboardSkeleton() {
  return (
    <div className="space-y-8" aria-busy="true" aria-label="Loading dashboard">
      <div className="space-y-2">
        <Skeleton className="h-8 w-2/3 max-w-md" />
        <Skeleton className="h-4 w-1/2 max-w-sm" />
      </div>
      <Skeleton className="aspect-[16/9] w-full max-h-64 rounded-[var(--radius-lg)]" />
      <Skeleton className="h-28 w-full rounded-[var(--radius-lg)]" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {Array.from({ length: 5 }, (_, index) => (
          <Skeleton
            key={index}
            className="h-24 w-full rounded-[var(--radius-lg)]"
          />
        ))}
      </div>
      <Skeleton className="h-40 w-full rounded-[var(--radius-lg)]" />
    </div>
  );
}
