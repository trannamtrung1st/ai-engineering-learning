import type { ActorRole } from "@we-event/domain";

export type CheckinMethod = "Staff" | "Self";

export interface CheckinRecordRow {
  id: string;
  registrationId: string;
  eventId: string;
  checkinAt: string;
  method: CheckinMethod;
  operatorId: string | null;
  createdAt: string;
}

export interface ActorContext {
  actorId: string;
  actorRole: ActorRole;
}

export interface CheckinAuditInput {
  eventId: string;
  registrationId: string;
  checkinId: string;
  action: string;
  actorId: string;
  actorRole: ActorRole;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}

export interface StaffCheckinInput {
  registrationId: string;
}

export interface AttendanceEntry {
  registrationId: string;
  participantId: string;
  state: string;
  checkinAt: string | null;
  checkinMethod: CheckinMethod | null;
}

export interface ListAttendanceQuery {
  page?: string;
  pageSize?: string;
  sort?: string;
}

export interface ListAttendanceOptions {
  sortColumn: string;
  sortDirection: "ASC" | "DESC";
  limit: number;
  offset: number;
}

export interface ListAttendanceResult {
  items: AttendanceEntry[];
  total: number;
}
