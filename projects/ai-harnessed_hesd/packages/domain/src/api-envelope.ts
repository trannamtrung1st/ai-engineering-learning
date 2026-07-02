import type { ErrorCode } from "./error-codes.js";

export interface ApiMeta {
  requestId: string;
  timestamp: string;
}

export interface ApiErrorBody {
  code: ErrorCode | string;
  message: string;
  details?: Record<string, unknown>;
}

export interface ApiSuccessEnvelope<T> {
  data: T;
  meta: ApiMeta;
  error: null;
}

export interface ApiErrorEnvelope {
  data: null;
  meta: ApiMeta;
  error: ApiErrorBody;
}

export type ApiEnvelope<T> = ApiSuccessEnvelope<T> | ApiErrorEnvelope;

export interface HealthPayload {
  status: "ok" | "degraded";
  db: "connected" | "disconnected";
  cache?: "connected" | "disconnected";
}

export function createMeta(requestId: string): ApiMeta {
  return {
    requestId,
    timestamp: new Date().toISOString(),
  };
}

export function successEnvelope<T>(data: T, requestId: string): ApiSuccessEnvelope<T> {
  return {
    data,
    meta: createMeta(requestId),
    error: null,
  };
}
