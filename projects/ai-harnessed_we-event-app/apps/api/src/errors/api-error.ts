import type { ValidationErrorCode } from "@we-event/domain";

export type AuthErrorCode = "UNAUTHENTICATED" | "FORBIDDEN";

export type ApiErrorCode =
  | ValidationErrorCode
  | AuthErrorCode
  | "INVALID_INPUT"
  | "INTERNAL_ERROR"
  | "NOT_FOUND"
  | "INVALID_STATE_TRANSITION";

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly statusCode: number;
  readonly details: Record<string, unknown>;

  constructor(options: {
    code: ApiErrorCode;
    message: string;
    statusCode: number;
    details?: Record<string, unknown>;
  }) {
    super(options.message);
    this.name = "ApiError";
    this.code = options.code;
    this.statusCode = options.statusCode;
    this.details = options.details ?? {};
  }
}

export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    requestId: string;
    timestamp: string;
  };
}

export function buildErrorEnvelope(
  code: string,
  message: string,
  requestId: string,
  details: Record<string, unknown> = {},
): ErrorEnvelope {
  return {
    error: {
      code,
      message,
      details,
      requestId,
      timestamp: new Date().toISOString(),
    },
  };
}
