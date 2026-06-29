import type { AttendanceStatus } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";
import type { SessionMonitorData } from "@/lib/session-monitor-api";

export type RosterRecord = SessionMonitorData["records"][number];

export interface AttendanceAuditEntry {
  id: string;
  editorId: string;
  editorDisplayName: string;
  previousStatus: AttendanceStatus;
  newStatus: AttendanceStatus;
  note: string | null;
  editedAt: string;
}

export interface ManualEditPayload {
  status: AttendanceStatus;
  note?: string;
}

export interface AttendanceRecordDto {
  id: string;
  sessionId: string;
  studentId: string;
  institutionalId: string;
  displayName: string;
  status: AttendanceStatus;
  checkedInAt: string | null;
}

export type ManualEditResult =
  | { ok: true; data: AttendanceRecordDto }
  | { ok: false; status: number; error: ApiErrorBody };

/** FR-11 — session attendance roster from authoritative API */
export async function fetchSessionRoster(sessionId: string): Promise<SessionMonitorData> {
  const res = await apiFetch<SessionMonitorData>(`/sessions/${sessionId}/attendance`);
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "RosterFetchFailed");
  }
  return res.data;
}

/** FR-11 / BR-10 — manual attendance correction */
export async function patchAttendanceRecord(
  recordId: string,
  payload: ManualEditPayload,
): Promise<ManualEditResult> {
  const res = await apiFetch<AttendanceRecordDto>(`/attendance/${recordId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

/** NFR-15 — append-only audit trail for manual edits */
export async function fetchAttendanceAuditLogs(
  recordId: string,
): Promise<AttendanceAuditEntry[]> {
  const res = await apiFetch<{ items: AttendanceAuditEntry[] }>(
    `/attendance/${recordId}/audit-logs`,
  );
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "AuditFetchFailed");
  }
  return res.data.items;
}
