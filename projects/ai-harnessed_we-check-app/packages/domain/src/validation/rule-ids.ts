/**
 * Validation rule identifiers and canonical error codes.
 * @see docs/technical/08-validation-rules.md
 */

export const ValidationRuleId = {
  VAL_01: "VAL-01",
  VAL_02: "VAL-02",
  VAL_03: "VAL-03",
  VAL_04: "VAL-04",
  VAL_05: "VAL-05",
  VAL_06: "VAL-06",
  VAL_07: "VAL-07",
  VAL_08: "VAL-08",
  VAL_09: "VAL-09",
  VAL_10: "VAL-10",
  VAL_11: "VAL-11",
  VAL_12: "VAL-12",
} as const;
export type ValidationRuleId =
  (typeof ValidationRuleId)[keyof typeof ValidationRuleId];

export const BusinessRuleId = {
  BR_01: "BR-01",
  BR_02: "BR-02",
  BR_03: "BR-03",
  BR_04: "BR-04",
  BR_05: "BR-05",
  BR_06: "BR-06",
  BR_07: "BR-07",
  BR_08: "BR-08",
  BR_09: "BR-09",
  BR_10: "BR-10",
  BR_11: "BR-11",
  BR_12: "BR-12",
} as const;
export type BusinessRuleId =
  (typeof BusinessRuleId)[keyof typeof BusinessRuleId];

export const ErrorCode = {
  InvalidFormat: "InvalidFormat",
  InvalidEmail: "InvalidEmail",
  PasswordTooShort: "PasswordTooShort",
  InvalidLength: "InvalidLength",
  InvalidInstitutionalId: "InvalidInstitutionalId",
  InvalidTimestamp: "InvalidTimestamp",
  InvalidPagination: "InvalidPagination",
  InvalidReturnUrl: "InvalidReturnUrl",
  InvalidEnum: "InvalidEnum",
  InvalidFile: "InvalidFile",
  ValidationFailed: "ValidationFailed",
  InvalidCredentials: "InvalidCredentials",
  AccountDeactivated: "AccountDeactivated",
  Unauthenticated: "Unauthenticated",
  Forbidden: "Forbidden",
  SessionNotActive: "SessionNotActive",
  ExpiredQr: "ExpiredQr",
  OutOfRadius: "OutOfRadius",
  DuplicateCheckIn: "DuplicateCheckIn",
  GpsDisabled: "GpsDisabled",
  SpoofSuspected: "SpoofSuspected",
  NotEnrolled: "NotEnrolled",
  TokenNotFound: "TokenNotFound",
  TokenAlreadyUsed: "TokenAlreadyUsed",
  RoomGpsRequired: "RoomGpsRequired",
  InvalidSessionState: "InvalidSessionState",
  EditWindowExpired: "EditWindowExpired",
  RateLimitExceeded: "RateLimitExceeded",
} as const;
export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

/** Maps business rules to their primary failure error codes. */
export const BUSINESS_RULE_ERROR_CODES: Readonly<
  Record<
    | typeof BusinessRuleId.BR_01
    | typeof BusinessRuleId.BR_02
    | typeof BusinessRuleId.BR_03
    | typeof BusinessRuleId.BR_04
    | typeof BusinessRuleId.BR_06
    | typeof BusinessRuleId.BR_07
    | typeof BusinessRuleId.BR_10
    | typeof BusinessRuleId.BR_11
    | typeof BusinessRuleId.BR_12,
    ErrorCode
  >
> = {
  [BusinessRuleId.BR_01]: ErrorCode.SessionNotActive,
  [BusinessRuleId.BR_02]: ErrorCode.OutOfRadius,
  [BusinessRuleId.BR_03]: ErrorCode.ExpiredQr,
  [BusinessRuleId.BR_04]: ErrorCode.DuplicateCheckIn,
  [BusinessRuleId.BR_06]: ErrorCode.Unauthenticated,
  [BusinessRuleId.BR_07]: ErrorCode.RoomGpsRequired,
  [BusinessRuleId.BR_10]: ErrorCode.EditWindowExpired,
  [BusinessRuleId.BR_11]: ErrorCode.TokenAlreadyUsed,
  [BusinessRuleId.BR_12]: ErrorCode.GpsDisabled,
};
