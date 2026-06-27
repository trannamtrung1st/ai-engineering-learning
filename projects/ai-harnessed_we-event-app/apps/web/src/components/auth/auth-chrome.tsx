import Link from "next/link";
import type { ReactNode } from "react";

import { CalendarDays } from "lucide-react";

export function AuthChrome({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-[var(--color-bg-default)]">
      <header className="border-b border-[var(--color-border-default)] bg-[var(--color-bg-surface)]">
        <div className="mx-auto flex h-14 max-w-[var(--container-max-app)] items-center px-4 sm:px-6">
          <Link
            href="/"
            className="flex items-center gap-2 rounded-[var(--radius-md)] font-[var(--font-weight-semibold)] text-[var(--color-text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]"
          >
            <CalendarDays
              className="h-5 w-5 text-[var(--color-action-primary-bg)]"
              aria-hidden
            />
            <span>We Event</span>
          </Link>
        </div>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 py-10 sm:px-6">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
