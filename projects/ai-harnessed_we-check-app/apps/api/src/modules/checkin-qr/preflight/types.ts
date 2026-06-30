import type { ErrorCode } from "@wecheck/domain";

export type PreflightErrorCode = ErrorCode | "SessionMismatch";

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
  outcome: PreflightErrorCode;
  message: string;
  errorCode: PreflightErrorCode;
}

export type PreflightResponse = PreflightSuccessResponse | PreflightFailureResponse;
