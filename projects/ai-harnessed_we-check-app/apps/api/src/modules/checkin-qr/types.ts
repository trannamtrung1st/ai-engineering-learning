import type { ErrorCode } from "@wecheck/domain";
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

export interface AttendanceCheckInRow {
  id: string;
  status: string;
  checkedInAt: Date | null;
  version: number;
}
