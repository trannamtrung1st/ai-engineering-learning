import type { SessionRoster } from "../attendance-ledger/types.js";

export type RosterUpdateReason =
  | "SessionOpened"
  | "CheckInRecorded"
  | "AttendanceCorrected"
  | "SessionClosed";

export interface RealtimeRosterEvent {
  eventId: string;
  type: "RosterUpdated";
  classSessionId: string;
  reason: RosterUpdateReason;
  occurredAt: string;
  correlationId: string | null;
  roster: SessionRoster;
}

export interface QrTokenIssuedTelemetry {
  eventId: string;
  type: "QrTokenIssued";
  classSessionId: string;
  tokenId: string | null;
  issuedAt: string;
  expiresAt: string;
  ttlMs: number;
  success: boolean;
  correlationId: string | null;
}

export interface CheckInAttemptTelemetry {
  eventId: string;
  type: "CheckInAttemptRecorded";
  classSessionId: string;
  studentUserId: string;
  outcome: string;
  success: boolean;
  occurredAt: string;
  correlationId: string | null;
}

export interface SessionLifecycleTelemetry {
  eventId: string;
  type: "SessionOpened" | "SessionClosed";
  classSessionId: string;
  actorUserId: string;
  beforeState: string;
  afterState: string;
  occurredAt: string;
  correlationId: string | null;
  initialRosterCount?: number;
}

export type OperationalTelemetryEvent =
  | QrTokenIssuedTelemetry
  | CheckInAttemptTelemetry
  | SessionLifecycleTelemetry;
