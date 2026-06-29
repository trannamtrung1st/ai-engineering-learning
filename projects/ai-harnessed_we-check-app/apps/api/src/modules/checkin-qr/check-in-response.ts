import { ErrorCode } from "@wecheck/domain";
import { ERROR_MESSAGES } from "../../errors/api-error.js";
import type { PreflightErrorCode } from "./types.js";

/** HTTP status for check-in domain failures per 05-api-design.md §6.3 */
export function checkInHttpStatus(errorCode: ErrorCode): number {
  switch (errorCode) {
    case ErrorCode.DuplicateCheckIn:
      return 409;
    case ErrorCode.TokenNotFound:
      return 404;
    case ErrorCode.SessionNotActive:
    case ErrorCode.NotEnrolled:
      return 403;
    default:
      return 400;
  }
}

export function checkInFailureMessage(errorCode: ErrorCode): string {
  return ERROR_MESSAGES[errorCode] ?? ERROR_MESSAGES[ErrorCode.ValidationFailed];
}

export function checkInSuccessMessage(): string {
  return "Điểm danh thành công";
}

const SESSION_MISMATCH_CODE = "SessionMismatch" satisfies PreflightErrorCode;

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
  return checkInFailureMessage(errorCode);
}

export { SESSION_MISMATCH_CODE };
