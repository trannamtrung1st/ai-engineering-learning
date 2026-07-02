/** Stored `audit_logs.action_type` values (schema CHECK constraint). */
export type DbAuditActionType =
  | "AttendanceUpdate"
  | "Export"
  | "SessionOpen"
  | "SessionClose"
  | "PolicyChange"
  | "EnrollmentImport"
  | "CheckInAttempt";

/** API-facing audit action filter values (GET /v1/audit-logs `actionType`). */
export type ApiAuditActionType =
  | "manual_update"
  | "admin_override"
  | "status_finalization"
  | "Export"
  | "export"
  | "CheckInAttemptRecorded"
  | "SessionOpen"
  | "SessionClose"
  | "PolicyChange"
  | "EnrollmentImport";

export type AttendanceAuditSubtype = "manual_update" | "admin_override" | "status_finalization";

export interface AuditLogQueryFilters {
  actorUserId?: string;
  targetType?: string;
  targetId?: string;
  classSessionId?: string;
  classSectionId?: string;
  actionType?: ApiAuditActionType;
  from?: string;
  to?: string;
  page: number;
  pageSize: number;
}

export interface AuditLogEntry {
  id: string;
  actionType: ApiAuditActionType;
  actorUserId: string | null;
  actorRole: string | null;
  actorDisplayName: string | null;
  targetType: string;
  targetId: string;
  studentUserId: string | null;
  classSessionId: string | null;
  classSectionId: string | null;
  oldStatus: string | null;
  newStatus: string | null;
  outcome: string | null;
  reason: string | null;
  scopeFilterSummary: string | null;
  format: string | null;
  correlationId: string | null;
  occurredAt: string;
}

export interface ResolvedAuditReadScope {
  institutionWide: boolean;
  classSectionIds: string[] | null;
  technicalOnly: boolean;
}
