"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useEffect } from "react";

import { ParticipantNav } from "@/components/participant/participant-nav";
import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@/components/ui/skeleton";
import {
  buildLoginRedirectUrl,
  isParticipantRole,
} from "@/lib/auth-redirect";
import { sessionDisplayName } from "@/lib/session-display-name";
import { useAuth } from "@/providers/auth-provider";

export function ParticipantShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { token, session, isLoading, signOut } = useAuth();

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
    if (!isParticipantRole(session.role)) {
      router.replace("/access-denied");
    }
  }, [isLoading, token, session, pathname, searchParams, router]);

  if (isLoading) {
    return (
      <AppShell role="participant" userDisplayName="Loading…">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </AppShell>
    );
  }

  if (!token || !session || !isParticipantRole(session.role)) {
    return (
      <AppShell role="participant" userDisplayName="Loading…">
        <div className="space-y-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-40 w-full" />
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell
      role="participant"
      userDisplayName={sessionDisplayName(session)}
      onSignOut={handleSignOut}
    >
      <ParticipantNav />
      <div className="mt-6">{children}</div>
    </AppShell>
  );
}
