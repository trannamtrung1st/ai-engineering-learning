import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";
import { checkInOutcomeMessages } from "@/lib/copy/checkin-messages";
import { mapCheckInOutcome } from "@/lib/check-in-api";

export type CheckInFlowAction =
  | "done"
  | "scan_again"
  | "retry_gps"
  | "show_gps_guide"
  | "show_camera_guide"
  | "go_history"
  | "close"
  | "contact_instructor";

/** Map server/API outcome codes to UI outcome codes (NFR-19, FR-09) */
export { mapCheckInOutcome };

/** Resolve primary CTA behavior for each check-in outcome (ui-states §4.3) */
export function resolveOutcomeAction(outcome: CheckInOutcomeCode): CheckInFlowAction {
  switch (outcome) {
    case "Present":
      return "done";
    case "ExpiredQr":
    case "TokenAlreadyUsed":
      return "scan_again";
    case "OutOfRadius":
    case "NetworkError":
      return "retry_gps";
    case "GpsDisabled":
      return "show_gps_guide";
    case "DuplicateCheckIn":
      return "go_history";
    case "SpoofSuspected":
      return "contact_instructor";
    case "SessionNotActive":
    case "NotEnrolled":
      return "close";
    default:
      return "retry_gps";
  }
}

export function geoFailureToOutcome(
  reason: "denied" | "timeout" | "unavailable",
): CheckInOutcomeCode {
  return reason === "denied" || reason === "timeout" || reason === "unavailable"
    ? "GpsDisabled"
    : "GpsDisabled";
}

export const LOCATION_CONSENT_KEY = "wecheck-location-consent";
export const CAMERA_CONSENT_KEY = "wecheck-camera-consent";

export function hasLocationConsent(): boolean {
  try {
    return localStorage.getItem(LOCATION_CONSENT_KEY) === "1";
  } catch {
    return false;
  }
}

export function markLocationConsent(): void {
  try {
    localStorage.setItem(LOCATION_CONSENT_KEY, "1");
  } catch {
    // ignore storage failures
  }
}

export function hasCameraConsent(): boolean {
  try {
    return localStorage.getItem(CAMERA_CONSENT_KEY) === "1";
  } catch {
    return false;
  }
}

export function markCameraConsent(): void {
  try {
    localStorage.setItem(CAMERA_CONSENT_KEY, "1");
  } catch {
    // ignore storage failures
  }
}

/** Format duplicate check-in detail with prior timestamp (AC-09, TC-AC-09-012). */
export function formatDuplicateCheckInDetail(priorCheckedInAt?: string): string {
  const base = checkInOutcomeMessages.DuplicateCheckIn.message;
  if (!priorCheckedInAt) return base;
  const formatted = new Date(priorCheckedInAt).toLocaleString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${base} lúc ${formatted}`;
}
