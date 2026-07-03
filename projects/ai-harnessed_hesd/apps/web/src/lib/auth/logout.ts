import { logout } from "../api/auth-api.js";
import { clearStudentAuthentication } from "./auth-gate.js";
import { clearAccessToken, getAccessToken } from "./session.js";

/** FLOW-15 voluntary logout — API ack then clear all client credentials (FR-38 AC-26 BR-24). */
export async function performVoluntaryLogout(): Promise<void> {
  if (getAccessToken()) {
    try {
      await logout();
    } catch {
      // Still clear local credentials when the network call fails.
    }
  }

  clearAccessToken();
  clearStudentAuthentication();
}

export const VOLUNTARY_LOGOUT_PATH = "/login";
