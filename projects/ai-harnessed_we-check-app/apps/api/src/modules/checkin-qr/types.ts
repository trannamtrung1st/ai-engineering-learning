import type { ErrorCode } from "@wecheck/domain";

export type PreflightErrorCode = ErrorCode | "SessionMismatch";
import type { SpoofMetadataInput } from "./spoof-heuristics.js";

export interface CheckInRequestBody {
  tokenId: string;
  latitude?: number;
  longitude?: number;
  gpsAvailable?: boolean;
  spoofMetadata?: SpoofMetadataInput;
}

export interface CheckInSuccessResponse {
  outcome: "Success";
  message: string;
  attendance: {
    status: "Present";
    checkedInAt: string;
  };
}

export interface CheckInFailureResponse {
  outcome: string;
  message: string;
  errorCode: ErrorCode;
  /** Present for DuplicateCheckIn — prior successful check-in time (AC-09). */
  priorCheckedInAt?: string;
}

export type CheckInResponse = CheckInSuccessResponse | CheckInFailureResponse;

export interface PreflightSessionSummary {
  classCode: string;
  subjectCode: string;
  roomName: string;
  status: string;
}

export interface PreflightSuccessResponse {
  outcome: "Valid";
  tokenId: string;
  sessionId: string;
  session: PreflightSessionSummary;
}

export interface PreflightFailureResponse {
  outcome: string;
  message: string;
  errorCode: PreflightErrorCode;
}

export type PreflightResponse = PreflightSuccessResponse | PreflightFailureResponse;

export interface QrTokenRow {
  id: string;
  sessionId: string;
  status: string;
  issuedAt: Date;
  expiresAt: Date;
  consumedByStudentId: string | null;
}

export interface SessionCheckInContext {
  id: string;
  classId: string;
  subjectId: string;
  status: string;
  openedAt: Date | null;
  closedAt: Date | null;
  scheduledStart: Date;
  roomLatitude: number;
  roomLongitude: number;
  gpsRadiusMeters: number;
}

export interface SessionDisplayContext extends SessionCheckInContext {
  classCode: string;
  subjectCode: string;
  roomName: string;
}

export interface AttendanceCheckInRow {
  id: string;
  status: string;
  checkedInAt: Date | null;
  version: number;
}
