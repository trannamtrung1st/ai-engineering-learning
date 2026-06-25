"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/cn";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

interface EventWorkspaceNavProps {
  eventId: string;
}

const BASE_LINKS = [
  { href: "", label: "Dashboard" },
  { href: "/registrations", label: "Registrations" },
  { href: "/waitlist", label: "Waitlist" },
  { href: "/check-in", label: "Check-in" },
  { href: "/eligibility", label: "Eligibility" },
] as const;

export function EventWorkspaceNav({ eventId }: EventWorkspaceNavProps) {
  const pathname = usePathname();
  const { isAdmin } = useOrganizerAuth();
  const basePath = `/organizer/events/${eventId}`;

  const links = isAdmin
    ? [...BASE_LINKS, { href: "/edit", label: "Edit" } as const]
    : BASE_LINKS;

  return (
    <nav
      aria-label="Event operations"
      className="border-b border-[var(--color-border-default)] bg-[var(--color-bg-surface)]"
    >
      <div className="flex gap-1 overflow-x-auto">
        {links.map((link) => {
          const href = `${basePath}${link.href}`;
          const active =
            link.href === ""
              ? pathname === basePath
              : pathname === href || pathname.startsWith(`${href}/`);
          return (
            <Link
              key={link.href}
              href={href}
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
