import type { SessionInfo } from "@/lib/session-api";

/** TopBar label per docs/ui-ux/06-app-layout-components.md — never expose actorId. */
export function sessionDisplayName(session: SessionInfo | null): string {
  const displayName = session?.displayName?.trim();
  if (displayName) {
    return displayName;
  }
  const email = session?.email?.trim();
  if (email) {
    return email;
  }
  return "Signed in user";
}
