import type { SessionState } from "../../components/ui/StatusBadge";
import { getAccessToken } from "../auth/session.js";
import { apiRequest } from "./client.js";
import { apiV1BaseUrl } from "./config.js";

export interface RosterCounts {
  present: number;
  late: number;
  pending: number;
  absent: number;
  excused: number;
  manualPresent: number;
  rejectedAttempts: number;
}

export interface RosterRow {
  studentUserId: string;
  studentCode: string;
  displayName: string;
  attendanceStatus: string;
  checkInMethod: string | null;
  checkInAt: string | null;
  latestAttemptOutcome: string | null;
}

export interface SessionRoster {
  classSessionId: string;
  state: SessionState;
  counts: RosterCounts;
  rows: RosterRow[];
}

export interface CorrectionPayload {
  status: string;
  reason: string;
}

export interface CorrectionResult {
  classSessionId: string;
  studentUserId: string;
  attendanceStatus: string;
  checkInMethod: string | null;
  checkInAt: string | null;
  previousStatus: string | null;
  reason: string;
}

export type RosterFetchResult =
  | { ok: true; roster: SessionRoster }
  | { ok: false; code: string; message: string };

export type CorrectionMutationResult =
  | { ok: true; data: CorrectionResult }
  | { ok: false; status: number; code: string; message: string };

interface RealtimeRosterEvent {
  roster: SessionRoster;
}

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export async function fetchSessionRoster(sessionId: string): Promise<RosterFetchResult> {
  const envelope = await apiRequest<SessionRoster>(`/class-sessions/${sessionId}/attendance`);

  if (envelope.data && !envelope.error) {
    return { ok: true, roster: envelope.data };
  }

  return {
    ok: false,
    code: envelope.error?.code ?? "RequestFailed",
    message: envelope.error?.message ?? "Không thể tải danh sách điểm danh.",
  };
}

export async function patchAttendanceCorrection(
  sessionId: string,
  studentUserId: string,
  payload: CorrectionPayload,
): Promise<CorrectionMutationResult> {
  const envelope = await apiRequest<CorrectionResult>(
    `/class-sessions/${sessionId}/attendance/${studentUserId}`,
    {
      method: "PATCH",
      body: payload,
      idempotencyKey: newIdempotencyKey(),
    },
  );

  if (envelope.data && !envelope.error) {
    return { ok: true, data: envelope.data };
  }

  const code = envelope.error?.code ?? "RequestFailed";
  const status =
    code === "EditWindowExpired"
      ? 409
      : code === "Forbidden" || code === "OutOfScope"
        ? 403
        : code === "ReasonRequired"
          ? 400
          : 400;

  return {
    ok: false,
    status,
    code,
    message: envelope.error?.message ?? "Không thể cập nhật điểm danh.",
  };
}

function parseSseChunk(buffer: string): { events: Array<{ event: string; data: string }>; rest: string } {
  const events: Array<{ event: string; data: string }> = [];
  const blocks = buffer.split("\n\n");
  const rest = blocks.pop() ?? "";

  for (const block of blocks) {
    if (!block.trim()) continue;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trim());
      }
    }
    if (dataLines.length > 0) {
      events.push({ event, data: dataLines.join("\n") });
    }
  }

  return { events, rest };
}

export interface RosterSubscriptionHandlers {
  onSnapshot: (roster: SessionRoster) => void;
  onUpdate: (roster: SessionRoster) => void;
  onDisconnect?: () => void;
}

/** Authenticated SSE via fetch streaming — FR-19 realtime roster */
export function subscribeSessionRosterEvents(
  sessionId: string,
  handlers: RosterSubscriptionHandlers,
): () => void {
  const abort = new AbortController();
  const token = getAccessToken();

  void (async () => {
    try {
      const response = await fetch(
        `${apiV1BaseUrl()}/class-sessions/${sessionId}/attendance/events`,
        {
          headers: {
            Accept: "text/event-stream",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: abort.signal,
        },
      );

      if (!response.ok || !response.body) {
        handlers.onDisconnect?.();
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (!abort.signal.aborted) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseSseChunk(buffer);
        buffer = parsed.rest;

        for (const chunk of parsed.events) {
          try {
            const payload = JSON.parse(chunk.data) as RealtimeRosterEvent;
            if (!payload.roster) continue;
            if (chunk.event === "roster.snapshot") {
              handlers.onSnapshot(payload.roster);
            } else {
              handlers.onUpdate(payload.roster);
            }
          } catch {
            // ignore malformed frames
          }
        }
      }
    } catch {
      if (!abort.signal.aborted) {
        handlers.onDisconnect?.();
      }
    }
  })();

  return () => abort.abort();
}
