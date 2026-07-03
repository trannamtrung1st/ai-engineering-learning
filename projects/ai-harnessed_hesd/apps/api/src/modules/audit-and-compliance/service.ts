import { randomUUID } from "node:crypto";
import type pg from "pg";
import type { AttendanceAuditSubtype, DbAuditActionType } from "./types.js";

export interface WriteAuditEventInput {
  id?: string;
  actorUserId?: string | null;
  actionType: DbAuditActionType;
  targetType: string;
  targetId: string;
  oldValue?: Record<string, unknown> | null;
  newValue?: Record<string, unknown> | null;
  reason?: string | null;
  scopeType?: string | null;
  scopeId?: string | null;
  correlationId?: string | null;
  ipAddress?: string | null;
}

/** Append-only audit write — M08 single write boundary (BR-22, NFR-10). */
export async function writeAuditEvent(
  client: pg.PoolClient,
  input: WriteAuditEventInput,
): Promise<string> {
  const id = input.id ?? randomUUID();
  await client.query(
    `
    INSERT INTO audit_logs (
      id, actor_user_id, action_type, target_type, target_id,
      old_value, new_value, reason, scope_type, scope_id, correlation_id, ip_address
    )
    VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10, $11, $12)
    `,
    [
      id,
      input.actorUserId ?? null,
      input.actionType,
      input.targetType,
      input.targetId,
      input.oldValue ? JSON.stringify(input.oldValue) : null,
      input.newValue ? JSON.stringify(input.newValue) : null,
      input.reason ?? null,
      input.scopeType ?? null,
      input.scopeId ?? null,
      input.correlationId ?? null,
      input.ipAddress ?? null,
    ],
  );
  return id;
}

export function buildAttendanceAuditPayload(params: {
  oldStatus: string | null;
  newStatus: string;
  studentUserId: string;
  classSessionId: string;
  classSectionId: string;
  actorRole: string | null;
  subtype: AttendanceAuditSubtype;
}): { oldValue: Record<string, unknown> | null; newValue: Record<string, unknown> } {
  return {
    oldValue: params.oldStatus ? { status: params.oldStatus } : null,
    newValue: {
      status: params.newStatus,
      studentUserId: params.studentUserId,
      classSessionId: params.classSessionId,
      classSectionId: params.classSectionId,
      actorRole: params.actorRole,
      auditActionSubtype: params.subtype,
    },
  };
}

export async function writeAttendanceAuditEvent(
  client: pg.PoolClient,
  params: {
    actorUserId: string | null;
    attendanceRecordId: string;
    oldStatus: string | null;
    newStatus: string;
    reason: string;
    studentUserId: string;
    classSessionId: string;
    classSectionId: string;
    actorRole: string | null;
    subtype: AttendanceAuditSubtype;
    correlationId?: string | null;
  },
): Promise<string> {
  const { oldValue, newValue } = buildAttendanceAuditPayload(params);
  return writeAuditEvent(client, {
    actorUserId: params.actorUserId,
    actionType: "AttendanceUpdate",
    targetType: "AttendanceRecord",
    targetId: params.attendanceRecordId,
    oldValue,
    newValue,
    reason: params.reason,
    correlationId: params.correlationId ?? null,
  });
}

export async function writeCheckInAttemptAuditEvent(
  client: pg.PoolClient,
  params: {
    attemptId: string;
    studentUserId: string;
    classSessionId: string;
    classSectionId: string;
    outcome: string;
    correlationId?: string | null;
  },
): Promise<string> {
  return writeAuditEvent(client, {
    actorUserId: params.studentUserId,
    actionType: "CheckInAttempt",
    targetType: "CheckInAttempt",
    targetId: params.attemptId,
    newValue: {
      outcome: params.outcome,
      studentUserId: params.studentUserId,
      classSessionId: params.classSessionId,
      classSectionId: params.classSectionId,
      attemptId: params.attemptId,
    },
    correlationId: params.correlationId ?? null,
  });
}
