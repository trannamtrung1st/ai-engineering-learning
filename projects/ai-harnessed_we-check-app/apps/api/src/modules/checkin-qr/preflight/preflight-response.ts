import { ErrorCode } from "@wecheck/domain";
import { ERROR_MESSAGES } from "../../../errors/api-error.js";
import { checkInFailureMessage } from "../check-in-response.js";
import type { PreflightErrorCode } from "./types.js";

export const SESSION_MISMATCH_CODE = "SessionMismatch" satisfies PreflightErrorCode;

/** HTTP status for preflight failures per 05-api-design.md §6.2 */
export function preflightHttpStatus(errorCode: PreflightErrorCode): number {
  switch (errorCode) {
    case ErrorCode.TokenNotFound:
      return 404;
    case ErrorCode.ExpiredQr:
    case ErrorCode.SessionNotActive:
    case ErrorCode.NotEnrolled:
    case ErrorCode.TokenAlreadyUsed:
    case SESSION_MISMATCH_CODE:
      return 403;
    default:
      return 400;
  }
}

export function preflightFailureMessage(errorCode: PreflightErrorCode): string {
  if (errorCode === SESSION_MISMATCH_CODE) {
    return "Mã QR không khớp với buổi học";
  }
  return checkInFailureMessage(errorCode as ErrorCode) ??
    ERROR_MESSAGES[ErrorCode.ValidationFailed];
}
