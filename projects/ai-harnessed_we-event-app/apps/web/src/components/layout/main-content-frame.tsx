import { type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface MainContentFrameProps {
  children: ReactNode;
  aside?: ReactNode;
  className?: string;
}

export function MainContentFrame({ children, aside, className }: MainContentFrameProps) {
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-[var(--container-max-app)] flex-1 flex-col gap-[var(--gap-section)] px-4 py-6 sm:px-6 lg:flex-row",
        className,
      )}
    >
      <div className="min-w-0 flex-1 space-y-[var(--gap-section)]">{children}</div>
      {aside ? (
        <aside className="w-full shrink-0 lg:w-80">{aside}</aside>
      ) : null}
    </div>
  );
}
