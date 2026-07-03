/** API enum labels — distinct from badge copy for filter options (FR-TTB-02). */
export const AUDIT_ACTION_TYPE_LABELS: Record<string, string> = {
  manual_update: "manual_update",
  admin_override: "admin_override",
  status_finalization: "status_finalization",
  Export: "Export",
  CheckInAttemptRecorded: "CheckInAttemptRecorded",
  SessionOpen: "SessionOpen",
  SessionClose: "SessionClose",
  PolicyChange: "PolicyChange",
  EnrollmentImport: "EnrollmentImport",
  AbsenceThresholdAlert: "AbsenceThresholdAlert",
};

export const AUDIT_TARGET_TYPE_LABELS: Record<string, string> = {
  AttendanceRecord: "AttendanceRecord",
  CheckInAttempt: "CheckInAttempt",
  ExportJob: "ExportJob",
  ClassSession: "ClassSession",
  AttendancePolicy: "AttendancePolicy",
};

export function formatAuditActionType(actionType: string): string {
  return AUDIT_ACTION_TYPE_LABELS[actionType] ?? actionType;
}
