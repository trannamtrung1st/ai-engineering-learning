import { AlertTriangle } from "lucide-react";
import { notificationCopy } from "@/lib/copy/notification-labels";
import { cn } from "@/lib/cn";

export interface AbsenceThresholdBadgeProps {
  className?: string;
}

/** FR-16 / AC-16 — persistent warning badge on affected subject rows */
export function AbsenceThresholdBadge({ className }: AbsenceThresholdBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border border-warning-300 bg-warning-50 px-2 py-0.5 text-small font-medium text-warning-800",
        className,
      )}
      data-testid="absence-threshold-badge"
    >
      <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
      {notificationCopy.historyBadge}
    </span>
  );
}
