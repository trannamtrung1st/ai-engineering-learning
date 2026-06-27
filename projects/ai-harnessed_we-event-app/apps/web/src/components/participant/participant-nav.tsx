"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { participantNavItems } from "@/lib/app-context";
import { cn } from "@/lib/cn";

export function ParticipantNav() {
  const pathname = usePathname();
  const links = participantNavItems;

  return (
    <nav
      aria-label="Participant"
      className="border-b border-[var(--color-border-default)] bg-[var(--color-bg-surface)]"
    >
      <div className="mx-auto flex max-w-[var(--container-max-app)] gap-1 overflow-x-auto px-4 sm:px-6">
        {links.map((link) => {
          const active =
            pathname === link.href || pathname.startsWith(`${link.href}/`);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                "whitespace-nowrap border-b-2 px-3 py-3 text-[length:var(--font-size-sm)] font-[var(--font-weight-medium)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-action-focus-ring)]",
                active
                  ? "border-[var(--color-action-primary-bg)] text-[var(--color-text-primary)]"
                  : "border-transparent text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]",
              )}
              aria-current={active ? "page" : undefined}
            >
              {link.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
