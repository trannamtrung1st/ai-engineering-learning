"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import { organizerNavItems } from "@/lib/app-context";
import {
  buildLoginRedirectUrl,
  isOrganizerRole,
} from "@/lib/auth-redirect";
import { sessionDisplayName } from "@/lib/session-display-name";
import { useOrganizerAuth } from "@/providers/organizer-auth-provider";

export function OrganizerShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { token, session, isAdmin, isLoading, signOut } = useOrganizerAuth();

  const appRole = isAdmin ? "organizer-admin" : "organizer-staff";

  const handleSignOut = () => {
    signOut();
    router.replace("/login");
  };

  useEffect(() => {
    if (isLoading) {
      return;
    }
    if (!token || !session) {
      const search = searchParams.toString();
      router.replace(buildLoginRedirectUrl(pathname, search));
      return;
    }
    if (!isOrganizerRole(session.role)) {
      router.replace("/access-denied");
    }
  }, [isLoading, token, session, pathname, searchParams, router]);

  if (isLoading) {
    return (
      <AppShell role="organizer-admin" userDisplayName="Loading…">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </AppShell>
    );
  }

  if (!token || !session || !isOrganizerRole(session.role)) {
    return (
      <AppShell role="organizer-admin" userDisplayName="Loading…">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      role={appRole}
      navItems={organizerNavItems}
      userDisplayName={sessionDisplayName(session)}
      onSignOut={handleSignOut}
    >
      <div>{children}</div>
    </AppShell>
  );
}
