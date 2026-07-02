import type { ApiEnvelope } from "@attendly/domain";
import { apiRequest } from "./client.js";

export interface GpsPayload {
  latitude: number;
  longitude: number;
  accuracyMeters: number;
}

export interface CheckInRequest {
  qrToken: string;
  clientTimestamp: string;
  gps?: GpsPayload;
  idempotencyKey?: string;
}

export interface CheckInSuccessData {
  outcome: "Success";
  attendanceStatus: "Present" | "Late";
  classSessionId: string;
  checkInAt: string;
}

export interface CheckInErrorDetails {
  classSessionId?: string;
  attendanceStatus?: string;
  checkInAt?: string;
}

export type CheckInApiResult =
  | { ok: true; data: CheckInSuccessData }
  | {
      ok: false;
      status: number;
      code: string;
      message: string;
      details?: CheckInErrorDetails;
    };

function clientTimestampNow(): string {
  return new Date().toISOString();
}

export async function submitCheckIn(request: CheckInRequest): Promise<CheckInApiResult> {
  const envelope = await apiRequest<CheckInSuccessData>("/check-ins", {
    method: "POST",
    body: {
      qrToken: request.qrToken,
      clientTimestamp: request.clientTimestamp || clientTimestampNow(),
      ...(request.gps ? { gps: request.gps } : {}),
    },
    idempotencyKey: request.idempotencyKey,
  });

  if (envelope.data?.outcome === "Success") {
    return { ok: true, data: envelope.data };
  }

  return {
    ok: false,
    status: envelope.error ? inferStatus(envelope) : 422,
    code: envelope.error?.code ?? "CheckInFailed",
    message: envelope.error?.message ?? "Không thể điểm danh.",
    details: envelope.error?.details as CheckInErrorDetails | undefined,
  };
}

function inferStatus<T>(envelope: ApiEnvelope<T>): number {
  const code = envelope.error?.code;
  if (code === "DuplicateCheckIn") {
    return 409;
  }
  if (code === "Unauthenticated") {
    return 401;
  }
  return 422;
}
