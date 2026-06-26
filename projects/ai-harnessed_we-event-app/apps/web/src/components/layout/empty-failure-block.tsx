import { type ReactNode } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { cn } from "@/lib/cn";

export interface EmptyFailureBlockProps {
  variant: "empty" | "failure";
  title: string;
  description: string;
  actionLabel?: string;
  onAction?: () => void;
  children?: ReactNode;
  className?: string;
}

export function EmptyFailureBlock({
  variant,
  title,
  description,
  actionLabel,
  onAction,
  children,
  className,
}: EmptyFailureBlockProps) {
  if (variant === "failure") {
    const showAction = actionLabel && onAction;

    return (
      <div className={cn(className)}>
        <Alert variant="error" title={title}>
          {description}
          {children}
          {showAction ? (
            <div className="mt-3">
              <Button size="sm" variant="secondary" onClick={onAction}>
                {actionLabel}
              </Button>
            </div>
          ) : null}
        </Alert>
      </div>
    );
  }

  return (
    <EmptyState
      className={className}
      title={title}
      description={description}
      actionLabel={actionLabel}
      onAction={onAction}
    />
  );
}
