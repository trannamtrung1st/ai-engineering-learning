import type { SessionState } from "./types.js";

export type OpenTransitionResult =
  | { allowed: true }
  | { allowed: false; code: "InvalidSessionTransition"; fromState: SessionState };

export type CloseTransitionResult =
  | { allowed: true; idempotent: false }
  | { allowed: true; idempotent: true }
  | { allowed: false; code: "InvalidSessionTransition"; fromState: SessionState };

/** VR-SS-02 — open is allowed only from Scheduled. */
export function validateOpenTransition(state: SessionState): OpenTransitionResult {
  if (state === "Scheduled") {
    return { allowed: true };
  }
  return { allowed: false, code: "InvalidSessionTransition", fromState: state };
}

/** VR-SS-03 — close is allowed only from Open; Closed is idempotent. */
export function validateCloseTransition(state: SessionState): CloseTransitionResult {
  if (state === "Open") {
    return { allowed: true, idempotent: false };
  }
  if (state === "Closed") {
    return { allowed: true, idempotent: true };
  }
  return { allowed: false, code: "InvalidSessionTransition", fromState: state };
}

/** BR-01 / BR-02 — session must be Open for successful check-in (exported for downstream modules). */
export function sessionCheckInGate(
  state: SessionState,
): "Open" | "SessionNotOpen" | "SessionClosed" {
  if (state === "Open") return "Open";
  if (state === "Closed") return "SessionClosed";
  return "SessionNotOpen";
}
