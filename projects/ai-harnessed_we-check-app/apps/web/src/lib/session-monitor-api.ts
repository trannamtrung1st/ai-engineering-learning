import { apiFetch } from "@/lib/api-client";

export interface SessionMonitorRecord {
  id: string;
  studentId: string;
  institutionalId: string;
  displayName: string;
  status: string;
  checkedInAt: string | null;
  spoofSuspected?: boolean;
}

export interface SessionMonitorSummary {
  enrolled: number;
  pending: number;
  present: number;
  absent: number;
  excused: number;
  rejected: number;
}

export interface SessionMonitorData {
  summary: SessionMonitorSummary;
  records: SessionMonitorRecord[];
  alerts: {
    codeSharing: boolean;
  };
}

/** FR-15 — poll live attendance + security alerts for instructor monitor */
export async function fetchSessionMonitor(sessionId: string): Promise<SessionMonitorData> {
  const res = await apiFetch<SessionMonitorData>(`/sessions/${sessionId}/attendance`);
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "MonitorFetchFailed");
  }
  return res.data;
}

/** Preview-only: backdate auth session for AC-02c expired-session browser gate */
export async function previewExpireSession(): Promise<void> {
  const res = await apiFetch<{ ok: boolean }>("/auth/preview/expire-session", {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "PreviewExpireFailed");
  }
}
