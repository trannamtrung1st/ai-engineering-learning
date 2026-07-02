import type { ApiAuditActionType, AttendanceAuditSubtype, AuditLogQueryFilters } from "./types.js";

const API_ACTION_TYPES = new Set<string>([
  "manual_update",
  "admin_override",
  "status_finalization",
  "Export",
  "export",
  "CheckInAttemptRecorded",
  "SessionOpen",
  "SessionClose",
  "PolicyChange",
  "EnrollmentImport",
]);

export function parseAuditLogQuery(
  query: Record<string, unknown>,
): { ok: true; filters: AuditLogQueryFilters } | { ok: false; code: "InvalidFilter" | "InvalidPayload" } {
  const page = Math.max(1, Number.parseInt(String(query.page ?? "1"), 10) || 1);
  const rawSize = Number.parseInt(String(query.pageSize ?? "25"), 10) || 25;
  const pageSize = Math.min(100, Math.max(1, rawSize));

  const actionTypeRaw = query.actionType;
  if (actionTypeRaw !== undefined && typeof actionTypeRaw !== "string") {
    return { ok: false, code: "InvalidPayload" };
  }
  if (actionTypeRaw && !API_ACTION_TYPES.has(actionTypeRaw)) {
    return { ok: false, code: "InvalidFilter" };
  }

  const actorUserId =
    typeof query.actorUserId === "string" && query.actorUserId.length > 0
      ? query.actorUserId
      : undefined;
  const targetType =
    typeof query.targetType === "string" && query.targetType.length > 0
      ? query.targetType
      : undefined;
  const targetId =
    typeof query.targetId === "string" && query.targetId.length > 0 ? query.targetId : undefined;
  const classSessionId =
    typeof query.classSessionId === "string" && query.classSessionId.length > 0
      ? query.classSessionId
      : undefined;
  const classSectionId =
    typeof query.classSectionId === "string" && query.classSectionId.length > 0
      ? query.classSectionId
      : undefined;
  const from = typeof query.from === "string" && query.from.length > 0 ? query.from : undefined;
  const to = typeof query.to === "string" && query.to.length > 0 ? query.to : undefined;

  if (from && Number.isNaN(Date.parse(from))) {
    return { ok: false, code: "InvalidFilter" };
  }
  if (to && Number.isNaN(Date.parse(to))) {
    return { ok: false, code: "InvalidFilter" };
  }

  return {
    ok: true,
    filters: {
      actorUserId,
      targetType,
      targetId,
      classSessionId,
      classSectionId,
      actionType: actionTypeRaw as ApiAuditActionType | undefined,
      from,
      to,
      page,
      pageSize,
    },
  };
}

export function normalizeApiActionType(value: string): ApiAuditActionType {
  if (value === "export") return "Export";
  return value as ApiAuditActionType;
}

export function apiActionTypeToDbFilter(
  actionType: ApiAuditActionType,
): { dbActionTypes: string[]; attendanceSubtype?: AttendanceAuditSubtype } {
  switch (actionType) {
    case "manual_update":
      return { dbActionTypes: ["AttendanceUpdate"], attendanceSubtype: "manual_update" };
    case "admin_override":
      return { dbActionTypes: ["AttendanceUpdate"], attendanceSubtype: "admin_override" };
    case "status_finalization":
      return { dbActionTypes: ["AttendanceUpdate"], attendanceSubtype: "status_finalization" };
    case "export":
    case "Export":
      return { dbActionTypes: ["Export"] };
    case "CheckInAttemptRecorded":
      return { dbActionTypes: ["CheckInAttempt"] };
    default:
      return { dbActionTypes: [actionType] };
  }
}

export function deriveApiActionType(row: {
  action_type: string;
  actor_user_id: string | null;
  new_value: Record<string, unknown> | null;
}): ApiAuditActionType {
  if (row.action_type === "AttendanceUpdate") {
    const subtype = row.new_value?.auditActionSubtype;
    if (subtype === "admin_override" || subtype === "manual_update" || subtype === "status_finalization") {
      return subtype;
    }
    if (row.actor_user_id === null) {
      return "status_finalization";
    }
    if (row.new_value?.actorRole === "AcademicAdmin" || row.new_value?.actorRole === "DepartmentAdmin") {
      return "admin_override";
    }
    return "manual_update";
  }
  if (row.action_type === "CheckInAttempt") {
    return "CheckInAttemptRecorded";
  }
  if (row.action_type === "Export") {
    return "Export";
  }
  return row.action_type as ApiAuditActionType;
}

export function extractStatus(value: Record<string, unknown> | null): string | null {
  if (!value || typeof value.status !== "string") return null;
  return value.status;
}
