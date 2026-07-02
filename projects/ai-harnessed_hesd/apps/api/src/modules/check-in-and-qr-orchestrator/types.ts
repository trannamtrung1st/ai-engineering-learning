import type { SessionState } from "../session-lifecycle/types.js";

export type QrTokenState = "Valid" | "Expired" | "Invalid";

export type CheckInOutcome =
  | "Success"
  | "ExpiredQr"
  | "SessionNotOpen"
  | "SessionClosed"
  | "NotEnrolled"
  | "DuplicateCheckIn"
  | "InvalidQr"
  | "GpsRequired"
  | "GpsDisabled"
  | "OutOfRadius"
  | "LowAccuracy";

export type AttendanceStatus = "Present" | "Late";

export interface ResolvedQrToken {
  id: string;
  classSessionId: string;
  state: QrTokenState;
  expiresAt: string;
  issuedAt: string;
}

export interface CurrentQrResult {
  classSessionId: string;
  tokenState: QrTokenState;
  expiresAt: string;
  qrPayload: string;
}

export interface CheckInSuccessResult {
  outcome: "Success";
  attendanceStatus: AttendanceStatus;
  classSessionId: string;
  checkInAt: string;
}

export interface CheckInFailureResult {
  outcome: Exclude<CheckInOutcome, "Success">;
  classSessionId?: string;
  details?: Record<string, unknown>;
}

export type CheckInCommandResult = CheckInSuccessResult | CheckInFailureResult;

export interface EffectivePolicy {
  presentWindowMinutes: number;
  lateWindowMinutes: number;
  gpsRequired: boolean;
  gpsRadiusMeters: number | null;
  gpsMinAccuracyMeters: number | null;
}

export interface SessionContext {
  id: string;
  classSectionId: string;
  state: SessionState;
  openedAt: string | null;
}

export interface GpsPayload {
  latitude: number;
  longitude: number;
  accuracyMeters: number;
}
