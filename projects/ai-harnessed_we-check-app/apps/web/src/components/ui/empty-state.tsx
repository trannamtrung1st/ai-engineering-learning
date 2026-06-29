import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 px-4 py-12 text-center",
        className,
      )}
    >
      <Icon className="h-10 w-10 text-text-secondary" aria-hidden="true" />
      <h2 className="text-h2 font-semibold text-text-primary">{title}</h2>
      {description ? (
        <p className="max-w-md text-body text-text-secondary">{description}</p>
      ) : null}
      {action}
    </div>
  );
}
