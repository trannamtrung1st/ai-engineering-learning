const PARTICIPANT_ROLES = new Set(["Participant"]);
const ORGANIZER_ROLES = new Set(["OrganizerAdmin", "OrganizerStaff"]);

export function buildLoginRedirectUrl(pathname: string, search: string): string {
  const path = `${pathname}${search ? `?${search}` : ""}`;
  return `/login?returnUrl=${encodeURIComponent(path)}`;
}

export function isSafeReturnUrl(returnUrl: string | null | undefined): returnUrl is string {
  if (!returnUrl) {
    return false;
  }
  if (!returnUrl.startsWith("/") || returnUrl.startsWith("//")) {
    return false;
  }
  if (returnUrl.startsWith("/login") || returnUrl.startsWith("/signup")) {
    return false;
  }
  return true;
}

export function resolvePostAuthRedirect(
  returnUrl: string | null | undefined,
  role: string,
): string {
  if (isSafeReturnUrl(returnUrl)) {
    return returnUrl;
  }
  if (ORGANIZER_ROLES.has(role)) {
    return "/organizer/events";
  }
  return "/events";
}

export function isParticipantRole(role: string | undefined): boolean {
  return role !== undefined && PARTICIPANT_ROLES.has(role);
}

export function isOrganizerRole(role: string | undefined): boolean {
  return role !== undefined && ORGANIZER_ROLES.has(role);
}
