/**
 * Canonical domain enumerations — mirrored in PostgreSQL ENUM types.
 * @see docs/technical/03-domain-model.md §3
 */

export const UserRole = {
  Student: "Student",
  Instructor: "Instructor",
  TrainingOfficeAdmin: "TrainingOfficeAdmin",
} as const;
export type UserRole = (typeof UserRole)[keyof typeof UserRole];

export const SessionStatus = {
  Draft: "Draft",
  Active: "Active",
  Closed: "Closed",
  Cancelled: "Cancelled",
} as const;
export type SessionStatus = (typeof SessionStatus)[keyof typeof SessionStatus];

export const TERMINAL_SESSION_STATUSES: ReadonlySet<SessionStatus> = new Set([
  SessionStatus.Closed,
  SessionStatus.Cancelled,
]);

export const AttendanceStatus = {
  Pending: "Pending",
  Present: "Present",
  Absent: "Absent",
  Excused: "Excused",
  Rejected: "Rejected",
} as const;
export type AttendanceStatus =
  (typeof AttendanceStatus)[keyof typeof AttendanceStatus];

export const QrTokenStatus = {
  Valid: "Valid",
  Expired: "Expired",
  Consumed: "Consumed",
} as const;
export type QrTokenStatus = (typeof QrTokenStatus)[keyof typeof QrTokenStatus];

export const TERMINAL_QR_TOKEN_STATUSES: ReadonlySet<QrTokenStatus> = new Set([
  QrTokenStatus.Expired,
  QrTokenStatus.Consumed,
]);

export const CheckInOutcome = {
  Success: "Success",
  ExpiredQr: "ExpiredQr",
  OutOfRadius: "OutOfRadius",
  DuplicateCheckIn: "DuplicateCheckIn",
  GpsDisabled: "GpsDisabled",
  Unauthenticated: "Unauthenticated",
  SessionNotActive: "SessionNotActive",
  SpoofSuspected: "SpoofSuspected",
  NotEnrolled: "NotEnrolled",
  TokenNotFound: "TokenNotFound",
} as const;
export type CheckInOutcome =
  (typeof CheckInOutcome)[keyof typeof CheckInOutcome];

export const NotificationType = {
  AbsenceThresholdWarning: "AbsenceThresholdWarning",
} as const;
export type NotificationType =
  (typeof NotificationType)[keyof typeof NotificationType];

export const RosterImportStatus = {
  Processing: "Processing",
  Completed: "Completed",
  Failed: "Failed",
} as const;
export type RosterImportStatus =
  (typeof RosterImportStatus)[keyof typeof RosterImportStatus];

export const GeoPlatform = {
  Ios: "ios",
  Android: "android",
  Other: "other",
} as const;
export type GeoPlatform = (typeof GeoPlatform)[keyof typeof GeoPlatform];
