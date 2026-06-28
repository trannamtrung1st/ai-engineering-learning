import { apiFetch } from "@/lib/api-client";
import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";

export interface QrTokenDisplay {
  sessionId: string;
  tokenId: string;
  qrPayload: string;
  issuedAt: string;
  expiresAt: string;
  secondsRemaining: number;
}

export interface CheckInSubmitInput {
  tokenId: string;
  latitude: number;
  longitude: number;
  gpsAvailable?: boolean;
}

export interface CheckInSubmitResult {
  outcome: CheckInOutcomeCode;
  message?: string;
  requiresAuth?: boolean;
}

const OUTCOME_MAP: Record<string, CheckInOutcomeCode> = {
  Success: "Present",
  ExpiredQr: "ExpiredQr",
  OutOfRadius: "OutOfRadius",
  GpsDisabled: "GpsDisabled",
  DuplicateCheckIn: "DuplicateCheckIn",
  SpoofSuspected: "SpoofSuspected",
  SessionNotActive: "SessionNotActive",
  NotEnrolled: "NotEnrolled",
  TokenNotFound: "ExpiredQr",
  TokenAlreadyUsed: "ExpiredQr",
  Unauthenticated: "NetworkError",
  SessionExpired: "NetworkError",
};

export function mapCheckInOutcome(
  outcome: string,
  errorCode?: string,
): CheckInOutcomeCode {
  return OUTCOME_MAP[errorCode ?? outcome] ?? OUTCOME_MAP[outcome] ?? "NetworkError";
}

export async function fetchQrCurrent(sessionId: string): Promise<QrTokenDisplay> {
  const res = await apiFetch<QrTokenDisplay>(`/sessions/${sessionId}/qr/current`);
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "QrFetchFailed");
  }
  return res.data;
}

/** NFR-06 — submit check-in via authoritative API (BR-03 stale token rejection) */
export async function submitCheckIn(
  input: CheckInSubmitInput,
): Promise<CheckInSubmitResult> {
  const res = await apiFetch<{
    outcome: string;
    message?: string;
    errorCode?: string;
  }>("/check-in", {
    method: "POST",
    body: JSON.stringify({
      tokenId: input.tokenId,
      latitude: input.latitude,
      longitude: input.longitude,
      gpsAvailable: input.gpsAvailable ?? true,
    }),
  });

  if (res.ok) {
    return { outcome: "Present", message: res.data.message };
  }

  const errorCode = res.data.errorCode;
  if (res.status === 401 && (errorCode === "Unauthenticated" || errorCode === "SessionExpired")) {
    return { outcome: "NetworkError", requiresAuth: true };
  }

  return {
    outcome: mapCheckInOutcome(res.data.outcome ?? "", errorCode),
    message: res.data.message,
  };
}
