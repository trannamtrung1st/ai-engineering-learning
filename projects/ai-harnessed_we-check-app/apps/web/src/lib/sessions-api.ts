import type { SessionStatus } from "@wecheck/domain";
import { apiFetch, type ApiErrorBody } from "@/lib/api-client";

export interface SessionDto {
  id: string;
  instructorId: string;
  classId: string;
  subjectId: string;
  title: string;
  roomName: string;
  roomLatitude: number | null;
  roomLongitude: number | null;
  gpsRadiusMeters: number;
  scheduledStart: string;
  status: SessionStatus;
  openedAt: string | null;
  closedAt: string | null;
  enrollmentCount?: number;
}

export interface SessionDetail extends SessionDto {
  classCode: string;
  className: string;
  subjectCode: string;
  subjectName: string;
  presentCount?: number;
}

export interface SessionListItem extends SessionDto {
  classCode: string;
  className: string;
  subjectCode: string;
  subjectName: string;
  presentCount?: number;
}

export interface SessionListResponse {
  items: SessionListItem[];
  totalCount: number;
}

export interface CreateSessionPayload {
  classId: string;
  subjectId: string;
  title: string;
  roomName: string;
  roomLatitude: number | null;
  roomLongitude: number | null;
  gpsRadiusMeters: number;
  scheduledStart: string;
}

export interface PatchSessionPayload {
  title?: string;
  roomName?: string;
  roomLatitude?: number | null;
  roomLongitude?: number | null;
  gpsRadiusMeters?: number;
  scheduledStart?: string;
}

export type SessionMutationResult =
  | { ok: true; data: SessionDto }
  | { ok: false; status: number; error: ApiErrorBody };

export async function fetchSessions(): Promise<SessionListResponse> {
  const res = await apiFetch<SessionListResponse>("/sessions");
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "SessionsFetchFailed");
  }
  return res.data;
}

export async function fetchSession(sessionId: string): Promise<SessionDetail> {
  const res = await apiFetch<SessionDetail>(`/sessions/${sessionId}`);
  if (!res.ok) {
    throw new Error(res.data.errorCode ?? "SessionFetchFailed");
  }
  return res.data;
}

export async function createSession(
  payload: CreateSessionPayload,
): Promise<SessionMutationResult> {
  const res = await apiFetch<SessionDto>("/sessions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function updateSession(
  sessionId: string,
  payload: PatchSessionPayload,
): Promise<SessionMutationResult> {
  const res = await apiFetch<SessionDto>(`/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function openSession(sessionId: string): Promise<SessionMutationResult> {
  const res = await apiFetch<SessionDto>(`/sessions/${sessionId}/open`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function closeSession(sessionId: string): Promise<SessionMutationResult> {
  const res = await apiFetch<SessionDto>(`/sessions/${sessionId}/close`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}

export async function cancelSession(sessionId: string): Promise<SessionMutationResult> {
  const res = await apiFetch<SessionDto>(`/sessions/${sessionId}/cancel`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    return { ok: false, status: res.status, error: res.data };
  }
  return { ok: true, data: res.data };
}
