import { apiFetch, type ApiErrorBody } from "@/lib/api-client";
import { detectMobilePlatform } from "@/lib/detect-platform";
import type { CheckInOutcomeCode } from "@/lib/copy/checkin-messages";

export interface QrTokenDisplay {
  sessionId: string;
  tokenId: string;
  qrPayload: string;
  issuedAt: string;
  expiresAt: string;
  secondsRemaining: number;
}

export interface SpoofMetadataInput {
  mockLocationDetected?: boolean;
  accuracyMeters?: number;
  platform?: "ios" | "android" | "other";
}

export interface CheckInSubmitInput {
  tokenId: string;
  latitude: number;
  longitude: number;
  gpsAvailable?: boolean;
  spoofMetadata?: SpoofMetadataInput;
}

export interface CheckInSubmitResult {
  outcome: CheckInOutcomeCode;
  message?: string;
  priorCheckedInAt?: string;
  requiresAuth?: boolean;
  sessionExpired?: boolean;
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
  TokenAlreadyUsed: "TokenAlreadyUsed",
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

function buildSpoofMetadata(input: CheckInSubmitInput): SpoofMetadataInput {
  const platform = detectMobilePlatform();
  const resolvedPlatform =
    input.spoofMetadata?.platform ??
    (platform === "ios" ? "ios" : platform === "android" ? "android" : "other");

  return {
    mockLocationDetected: input.spoofMetadata?.mockLocationDetected ?? false,
    platform: resolvedPlatform,
    accuracyMeters: input.spoofMetadata?.accuracyMeters,
  };
}

/** NFR-06 — submit check-in via authoritative API (BR-03 stale token rejection) */
export async function submitCheckIn(
  input: CheckInSubmitInput,
): Promise<CheckInSubmitResult> {
  const spoofMetadata = buildSpoofMetadata(input);
  const body: Record<string, unknown> = {
    tokenId: input.tokenId,
    gpsAvailable: input.gpsAvailable ?? true,
  };

  if (input.gpsAvailable !== false) {
    body.latitude = input.latitude;
    body.longitude = input.longitude;
  }

  if (spoofMetadata) {
    body.spoofMetadata = spoofMetadata;
  }

  const res = await apiFetch<{
    outcome: string;
    message?: string;
    errorCode?: string;
    priorCheckedInAt?: string;
  }>("/check-in", {
    method: "POST",
    body: JSON.stringify(body),
  });

  if (res.ok) {
    return { outcome: "Present", message: res.data.message };
  }

  const errorCode = res.data.errorCode;
  if (res.status === 401 && (errorCode === "Unauthenticated" || errorCode === "SessionExpired")) {
    return {
      outcome: "NetworkError",
      requiresAuth: true,
      sessionExpired: errorCode === "SessionExpired",
    };
  }

  const failure = res.data as ApiErrorBody & { priorCheckedInAt?: string };
  return {
    outcome: mapCheckInOutcome(failure.outcome ?? "", errorCode),
    message: failure.message,
    priorCheckedInAt: failure.priorCheckedInAt,
  };
}

const NETWORK_RETRY_DELAYS_MS = [0, 1000, 3000];

/** Network retry up to 3 attempts within ~30 s (production-ui-quality-bar §5.1) */
export async function submitCheckInWithRetry(
  input: CheckInSubmitInput,
): Promise<CheckInSubmitResult> {
  let lastResult: CheckInSubmitResult = { outcome: "NetworkError" };

  for (let attempt = 0; attempt < NETWORK_RETRY_DELAYS_MS.length; attempt += 1) {
    if (attempt > 0) {
      await new Promise((resolve) => {
        setTimeout(resolve, NETWORK_RETRY_DELAYS_MS[attempt]);
      });
    }

    try {
      const result = await submitCheckIn(input);
      if (result.requiresAuth) return result;
      if (result.outcome !== "NetworkError") return result;
      lastResult = result;
    } catch {
      lastResult = { outcome: "NetworkError" };
    }
  }

  return lastResult;
}
