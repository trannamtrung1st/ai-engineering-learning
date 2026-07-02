/** Stable API error codes shared by backend and frontend (docs/technical/08-validation-rules.md §6.2). */
export const ErrorCode = {
  Unauthenticated: "Unauthenticated",
  Forbidden: "Forbidden",
  OutOfScope: "OutOfScope",
  SessionNotOpen: "SessionNotOpen",
  SessionClosed: "SessionClosed",
  ExpiredQr: "ExpiredQr",
  InvalidQr: "InvalidQr",
  InvalidSessionTransition: "InvalidSessionTransition",
  NotEnrolled: "NotEnrolled",
  DuplicateCheckIn: "DuplicateCheckIn",
  GpsRequired: "GpsRequired",
  GpsDisabled: "GpsDisabled",
  OutOfRadius: "OutOfRadius",
  LowAccuracy: "LowAccuracy",
  InvalidGpsPayload: "InvalidGpsPayload",
  InvalidPayload: "InvalidPayload",
  InvalidFilter: "InvalidFilter",
  UnsupportedFormat: "UnsupportedFormat",
  ReasonRequired: "ReasonRequired",
  EditWindowExpired: "EditWindowExpired",
  Conflict: "Conflict",
  SessionNotFound: "SessionNotFound",
  StudentNotFound: "StudentNotFound",
} as const;

export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

export const ERROR_CODE_GROUPS = {
  authentication: [ErrorCode.Unauthenticated],
  authorization: [ErrorCode.Forbidden, ErrorCode.OutOfScope],
  sessionAndToken: [
    ErrorCode.SessionNotOpen,
    ErrorCode.SessionClosed,
    ErrorCode.ExpiredQr,
    ErrorCode.InvalidQr,
    ErrorCode.InvalidSessionTransition,
  ],
  eligibility: [ErrorCode.NotEnrolled, ErrorCode.DuplicateCheckIn],
  gps: [
    ErrorCode.GpsRequired,
    ErrorCode.GpsDisabled,
    ErrorCode.OutOfRadius,
    ErrorCode.LowAccuracy,
    ErrorCode.InvalidGpsPayload,
  ],
  validation: [
    ErrorCode.InvalidPayload,
    ErrorCode.InvalidFilter,
    ErrorCode.UnsupportedFormat,
    ErrorCode.ReasonRequired,
    ErrorCode.EditWindowExpired,
  ],
} as const;

export function isErrorCode(value: string): value is ErrorCode {
  return Object.values(ErrorCode).includes(value as ErrorCode);
}
