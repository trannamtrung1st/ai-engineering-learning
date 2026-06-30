import { ErrorCode } from "@wecheck/domain";
import { ERROR_MESSAGES } from "../../errors/api-error.js";

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
