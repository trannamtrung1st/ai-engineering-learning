import { getAccessToken } from "./session.js";

export function isStaffAuthenticated(): boolean {
  return Boolean(getAccessToken());
}

export function buildStaffLoginRedirect(returnPath: string): string {
  const returnUrl = encodeURIComponent(returnPath);
  return `/login?returnUrl=${returnUrl}`;
}
