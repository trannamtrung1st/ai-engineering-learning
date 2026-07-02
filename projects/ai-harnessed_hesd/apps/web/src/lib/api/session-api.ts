import type { SessionState } from "../../components/ui/StatusBadge";
import type { ApiEnvelope } from "@attendly/domain";
import type { QrDisplayData } from "../../components/domain/QrDisplayPanel";
import { buildSessionListQueryString, type SessionListQueryState } from "../listing/session-list-query.js";
import { apiRequest } from "./client.js";

export interface ClassSessionSummary {
  classSessionId: string;
  classSectionId: string;
  sectionCode: string;
  courseName: string;
  roomCode: string | null;
  roomName: string | null;
  scheduledStartAt: string;
  scheduledEndAt: string;
  state: SessionState;
  openedAt: string | null;
  closedAt: string | null;
}

export interface PaginationMeta {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
}

export interface OpenSessionData {
  classSessionId: string;
  state: "Open";
  openedAt: string;
  qr: {
    expiresAt: string;
    qrPayload: string;
  };
}

export interface CloseSessionData {
  classSessionId: string;
  state: "Closed";
  closedAt: string;
  summary: {
    present: number;
    late: number;
    manualPresent: number;
    absent: number;
  };
}

export type SessionListResult =
  | {
      ok: true;
      items: ClassSessionSummary[];
      pagination: PaginationMeta;
    }
  | { ok: false; code: string; message: string };

export type SessionDetailResult =
  | { ok: true; session: ClassSessionSummary }
  | { ok: false; code: string; message: string };

export type SessionMutationResult<T> =
  | { ok: true; data: T }
  | { ok: false; status: number; code: string; message: string; details?: Record<string, unknown> };

export type CurrentQrResult =
  | { ok: true; qr: QrDisplayData }
  | { ok: false; code: string; message: string };

function readPagination(meta: ApiEnvelope<unknown>["meta"]): PaginationMeta {
  const pagination = (
    meta as ApiEnvelope<unknown>["meta"] & { pagination?: PaginationMeta }
  ).pagination;
  return {
    page: pagination?.page ?? 1,
    pageSize: pagination?.pageSize ?? 25,
    totalItems: pagination?.totalItems ?? 0,
    totalPages: pagination?.totalPages ?? 0,
  };
}

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export async function fetchClassSessions(query: SessionListQueryState): Promise<SessionListResult> {
  const envelope = await apiRequest<ClassSessionSummary[]>(
    `/class-sessions${buildSessionListQueryString(query)}`,
  );

  if (envelope.data && !envelope.error) {
    return {
      ok: true,
      items: envelope.data,
      pagination: readPagination(envelope.meta),
    };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải danh sách buổi học.",
  };
}

export async function fetchClassSessionById(sessionId: string): Promise<SessionDetailResult> {
  const envelope = await apiRequest<ClassSessionSummary>(`/class-sessions/${sessionId}`);

  if (envelope.data && !envelope.error) {
    return { ok: true, session: envelope.data };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải thông tin buổi học.",
  };
}

export async function openClassSession(sessionId: string): Promise<SessionMutationResult<OpenSessionData>> {
  const envelope = await apiRequest<OpenSessionData>(`/class-sessions/${sessionId}/open`, {
    method: "POST",
    body: {},
    idempotencyKey: newIdempotencyKey(),
  });

  if (envelope.data?.state === "Open") {
    return { ok: true, data: envelope.data };
  }

  return {
    ok: false,
    status: envelope.error?.code === "InvalidSessionTransition" ? 409 : 400,
    code: envelope.error?.code ?? "OpenFailed",
    message: envelope.error?.message ?? "Không thể mở buổi học.",
    details: envelope.error?.details as Record<string, unknown> | undefined,
  };
}

export async function closeClassSession(sessionId: string): Promise<SessionMutationResult<CloseSessionData>> {
  const envelope = await apiRequest<CloseSessionData>(`/class-sessions/${sessionId}/close`, {
    method: "POST",
    body: {},
    idempotencyKey: newIdempotencyKey(),
  });

  if (envelope.data?.state === "Closed") {
    return { ok: true, data: envelope.data };
  }

  return {
    ok: false,
    status: envelope.error?.code === "InvalidSessionTransition" ? 409 : 400,
    code: envelope.error?.code ?? "CloseFailed",
    message: envelope.error?.message ?? "Không thể đóng buổi học.",
    details: envelope.error?.details as Record<string, unknown> | undefined,
  };
}

export async function fetchCurrentQr(sessionId: string): Promise<CurrentQrResult> {
  const envelope = await apiRequest<{
    classSessionId: string;
    tokenState: QrDisplayData["tokenState"];
    expiresAt: string;
    qrPayload: string;
  }>(`/class-sessions/${sessionId}/qr/current`);

  if (envelope.data?.tokenState === "Valid" && envelope.data.qrPayload) {
    return {
      ok: true,
      qr: {
        qrPayload: envelope.data.qrPayload,
        expiresAt: envelope.data.expiresAt,
        tokenState: envelope.data.tokenState,
      },
    };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "QrUnavailable",
    message: envelope.error?.message ?? "Không thể tải mã QR hiện tại.",
  };
}

export function formatSessionLabel(session: Pick<ClassSessionSummary, "courseName" | "scheduledStartAt">): string {
  const when = new Intl.DateTimeFormat("vi-VN", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(session.scheduledStartAt));
  return `${session.courseName} · ${when}`;
}

export function formatRoomLabel(session: Pick<ClassSessionSummary, "roomCode" | "roomName">): string {
  if (session.roomCode && session.roomName) {
    return `${session.roomCode} · ${session.roomName}`;
  }
  return session.roomName ?? session.roomCode ?? "—";
}

export function formatScheduledAt(iso: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(iso));
}
