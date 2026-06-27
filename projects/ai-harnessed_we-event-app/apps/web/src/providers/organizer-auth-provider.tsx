"use client";

import { useAuth } from "@/providers/auth-provider";

export type OrganizerRole = "OrganizerAdmin" | "OrganizerStaff";

/** Organizer layouts reuse the shared credential session provider. */
export function OrganizerAuthProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}

export function useOrganizerAuth() {
  const auth = useAuth();
  return {
    token: auth.token,
    session: auth.session,
    isAdmin: auth.isAdmin,
    isStaff: auth.isStaff,
    isLoading: auth.isLoading,
    error: auth.error,
    signIn: auth.signIn,
    signOut: auth.signOut,
  };
}
