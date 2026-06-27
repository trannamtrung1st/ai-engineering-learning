import type {
  CertificateEligibilityState,
  EventState,
  RegistrationState,
} from "@we-event/domain";

import { ApiClientError, apiFetch } from "@/lib/api-client";
import { downloadBlob } from "@/lib/export-csv";
import type {
  EventListItem,
  EventRuleConfig,
  EventSummary,
  PaginatedResult,
  RegistrationStatus,
  SessionInfo,
} from "@/lib/participant-api";

export type { PaginatedResult, EventSummary, SessionInfo };

export const DEFAULT_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001";
/** Seeded organizer admin — must be a UUID (audit log actor columns). */
export const DEFAULT_ORGANIZER_ADMIN_ID =
  "00000000-0000-0000-0000-000000000099";
/** Seeded organizer staff for browser fixture pagination. */
export const DEFAULT_ORGANIZER_STAFF_ID =
  "00000000-0000-0000-0000-000000000098";

export interface DevSeedFixtures {
  bulkRegistrationsEventId: string;
  staffSub: string;
  staffAssignedEventIds: string[];
  participantSub: string;
  checkinEventId: string;
  checkinSelfDisabledEventId: string;
  checkinCloseBoundaryEventId: string;
  waitlistEventId: string;
  feedbackEventId: string;
  feedbackCloseBoundaryEventId: string;
}

export interface RuleConfigInput {
  capacity: number;
  waitlistEnabled?: boolean;
  registrationOpenAt: string;
  registrationCloseAt: string;
  checkinOpenAt: string;
  checkinCloseAt: string;
  feedbackRequired?: boolean;
  feedbackOpenAt: string;
  feedbackCloseAt: string;
}

export interface CreateEventInput {
  organizationId?: string;
  name: string;
  description?: string;
  location?: string;
  startAt: string;
  endAt: string;
  ruleConfig: RuleConfigInput;
}

export interface UpdateEventInput {
  name?: string;
  description?: string;
  location?: string;
  startAt?: string;
  endAt?: string;
  ruleConfig?: Partial<RuleConfigInput> & { registrationPaused?: boolean };
  reasonCode?: string;
  reasonText?: string;
}

export interface WaitlistListItem {
  waitlistEntryId: string;
  registrationId: string;
  participantId: string;
  position: number;
  enqueuedAt: string;
  state: RegistrationState;
}

export interface AttendanceEntry {
  registrationId: string;
  participantId: string;
  state: string;
  checkinAt: string | null;
  checkinMethod: "Staff" | "Self" | null;
}

export interface CheckinResult {
  checkinId: string;
  registrationId: string;
  eventId: string;
  participantId: string;
  checkinAt: string;
  method: "Staff" | "Self";
  operatorId: string | null;
  registrationState: RegistrationState;
}

export interface EligibilityListEntry {
  registrationId: string;
  participantId: string;
  registrationState: string;
  eligibility: {
    eligibilityId: string;
    eventId: string;
    registrationId: string;
    participantId: string;
    result: CertificateEligibilityState;
    reasonCode: string | null;
    reasonText: string | null;
    evaluatedAt: string | null;
    overriddenBy: string | null;
    updatedAt: string;
  };
}

export interface AuditLogEntry {
  id: string;
  eventId: string;
  entityType: string;
  entityId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode: string | null;
  reasonText: string | null;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  occurredAt: string;
}

export interface StatusHistoryEntry {
  id: string;
  registrationId: string;
  action: string;
  actorId: string;
  actorRole: string;
  reasonCode: string | null;
  reasonText: string | null;
  beforeState: string | null;
  afterState: string | null;
  occurredAt: string;
}

export interface EventDashboardMetrics {
  registrations: number;
  registeredSeats: number;
  waitlist: number;
  checkedIn: number;
  attended: number;
  eligible: number;
  notEligible: number;
  pendingEligibility: number;
  feedbackSubmitted: number;
  feedbackRequired: boolean;
  mandatoryFeedbackOutstanding: number;
}

export interface FetchEventsParams {
  page?: number;
  pageSize?: number;
  q?: string;
  state?: EventState;
  sort?: string;
}

export interface ListQueryParams {
  page?: number;
  pageSize?: number;
  sort?: string;
  state?: string;
  eligibility?: CertificateEligibilityState;
  registrationId?: string;
}

export interface DownloadEligibilityExportParams {
  eligibility?: CertificateEligibilityState;
}

export interface DevTokenResponse {
  token: string;
  sub: string;
  role: string;
  assignedEventIds?: string[];
}

function authInit(token: string, init?: RequestInit): RequestInit & { token: string } {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return { ...init, headers, token };
}

function idempotencyKey(): string {
  return crypto.randomUUID();
}

function buildQueryString(
  params: Record<string, string | number | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const query = search.toString();
  return query ? `?${query}` : "";
}

export function fetchSession(token: string): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/me", { token });
}

export function requestOrganizerDevToken(
  sub: string,
  role: "OrganizerAdmin" | "OrganizerStaff",
  assignedEventIds: string[] = [],
): Promise<DevTokenResponse> {
  return apiFetch<DevTokenResponse>("/dev/token", {
    method: "POST",
    body: JSON.stringify({ sub, role, assignedEventIds }),
    headers: { "Content-Type": "application/json" },
  });
}

export function fetchDevFixtures(): Promise<DevSeedFixtures> {
  return apiFetch<DevSeedFixtures>("/dev/fixtures");
}

export function fetchOrganizerEvents(
  token: string,
  params: FetchEventsParams = {},
): Promise<PaginatedResult<EventListItem>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    q: params.q,
    state: params.state,
    sort: params.sort,
  });
  return apiFetch<PaginatedResult<EventListItem>>(`/events${query}`, { token });
}

export function fetchOrganizerEvent(
  token: string,
  eventId: string,
): Promise<EventSummary> {
  return apiFetch<EventSummary>(`/events/${eventId}`, { token });
}

export function createEvent(
  token: string,
  input: CreateEventInput,
): Promise<EventSummary> {
  return apiFetch<EventSummary>(
    "/events",
    authInit(token, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function updateEvent(
  token: string,
  eventId: string,
  input: UpdateEventInput,
): Promise<EventSummary> {
  return apiFetch<EventSummary>(
    `/events/${eventId}`,
    authInit(token, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  );
}

function transitionEvent(
  token: string,
  eventId: string,
  action: string,
  body?: { reasonCode?: string; reasonText?: string },
): Promise<EventSummary> {
  return apiFetch<EventSummary>(
    `/events/${eventId}/${action}`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify(body ?? {}),
    }),
  );
}

export const publishEvent = (token: string, eventId: string) =>
  transitionEvent(token, eventId, "publish");

export const pauseEvent = (token: string, eventId: string) =>
  transitionEvent(token, eventId, "pause");

export const openRegistration = (token: string, eventId: string) =>
  transitionEvent(token, eventId, "open-registration");

export const closeRegistration = (token: string, eventId: string) =>
  transitionEvent(token, eventId, "close-registration");

export const startEvent = (token: string, eventId: string) =>
  transitionEvent(token, eventId, "start");

export const completeEvent = (token: string, eventId: string) =>
  transitionEvent(token, eventId, "complete");

export const cancelEvent = (
  token: string,
  eventId: string,
  reasonText: string,
  reasonCode?: string,
) => transitionEvent(token, eventId, "cancel", { reasonCode, reasonText });

export function fetchRegistrations(
  token: string,
  eventId: string,
  params: ListQueryParams = {},
): Promise<PaginatedResult<RegistrationStatus>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    sort: params.sort,
    state: params.state,
  });
  return apiFetch<PaginatedResult<RegistrationStatus>>(
    `/events/${eventId}/registrations${query}`,
    { token },
  );
}

export function fetchWaitlist(
  token: string,
  eventId: string,
  params: ListQueryParams = {},
): Promise<PaginatedResult<WaitlistListItem>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    sort: params.sort,
  });
  return apiFetch<PaginatedResult<WaitlistListItem>>(
    `/events/${eventId}/waitlist${query}`,
    { token },
  );
}

export function fetchAttendance(
  token: string,
  eventId: string,
  params: ListQueryParams = {},
): Promise<PaginatedResult<AttendanceEntry>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    sort: params.sort,
  });
  return apiFetch<PaginatedResult<AttendanceEntry>>(
    `/events/${eventId}/attendance${query}`,
    { token },
  );
}

export function staffCheckin(
  token: string,
  eventId: string,
  registrationId: string,
): Promise<CheckinResult> {
  return apiFetch<CheckinResult>(
    `/events/${eventId}/checkins`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify({ registrationId }),
      headers: { "Idempotency-Key": idempotencyKey() },
    }),
  );
}

export function fetchEligibility(
  token: string,
  eventId: string,
  params: ListQueryParams = {},
): Promise<PaginatedResult<EligibilityListEntry>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    sort: params.sort,
    eligibility: params.eligibility,
  });
  return apiFetch<PaginatedResult<EligibilityListEntry>>(
    `/events/${eventId}/eligibility${query}`,
    { token },
  );
}

export function revokeEligibility(
  token: string,
  eventId: string,
  registrationId: string,
  input: { reasonCode: string; reasonText: string },
): Promise<EligibilityListEntry["eligibility"]> {
  return apiFetch<EligibilityListEntry["eligibility"]>(
    `/events/${eventId}/eligibility/${registrationId}/revoke`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function fetchAuditLogs(
  token: string,
  eventId: string,
  params: ListQueryParams = {},
): Promise<PaginatedResult<AuditLogEntry>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    sort: params.sort,
  });
  return apiFetch<PaginatedResult<AuditLogEntry>>(
    `/events/${eventId}/audit-logs${query}`,
    { token },
  );
}

export function fetchStatusHistory(
  token: string,
  eventId: string,
  params: ListQueryParams = {},
): Promise<PaginatedResult<StatusHistoryEntry>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    sort: params.sort,
    registrationId: params.registrationId,
  });
  return apiFetch<PaginatedResult<StatusHistoryEntry>>(
    `/events/${eventId}/status-history${query}`,
    { token },
  );
}

export async function downloadEligibilityExport(
  token: string,
  eventId: string,
  params: DownloadEligibilityExportParams = {},
): Promise<{ filename: string; rowCount: number }> {
  const query = buildQueryString({
    type: "eligibility",
    eligibility: params.eligibility,
  });

  const normalizedPath = `/api/v1/events/${eventId}/export${query}`;
  const url =
    typeof window !== "undefined"
      ? normalizedPath
      : `${(process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:3001").replace(/\/$/, "")}${normalizedPath}`;

  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "text/csv",
    },
  });

  if (!response.ok) {
    let message = `Export failed (${response.status})`;
    try {
      const body = (await response.json()) as {
        error?: { message?: string; code?: string };
      };
      message = body.error?.message ?? message;
    } catch {
      // Non-JSON error body — keep default message.
    }
    throw new ApiClientError(message, response.status);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition");
  const filename =
    disposition?.match(/filename="([^"]+)"/)?.[1] ??
    `eligibility-${eventId}.csv`;

  downloadBlob(filename, blob);

  const rowCountHeader = response.headers.get("X-Export-Row-Count");
  const rowCount = rowCountHeader ? Number.parseInt(rowCountHeader, 10) : NaN;

  return {
    filename,
    rowCount: Number.isFinite(rowCount) ? rowCount : 0,
  };
}

export function fetchEventDashboardMetrics(
  token: string,
  eventId: string,
): Promise<EventDashboardMetrics> {
  return apiFetch<EventDashboardMetrics>(`/events/${eventId}/dashboard`, {
    token,
  });
}

export function countRegisteredSeats(
  ruleConfig: EventRuleConfig,
  registeredSeats: number,
  waitlist: number,
): { registered: number; capacity: number; waitlist: number } {
  return {
    registered: registeredSeats,
    capacity: ruleConfig.capacity,
    waitlist,
  };
}

const API_PREFIX = "/api/v1";

function coverUploadBaseUrl(): string {
  if (typeof window !== "undefined") {
    return "";
  }
  const base =
    process.env.API_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:3001";
  return base.replace(/\/$/, "");
}

export function uploadEventCoverImage(
  token: string,
  eventId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<EventSummary> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    formData.append("file", file);

    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as EventSummary);
        } catch {
          reject(new ApiClientError("Invalid upload response.", xhr.status));
        }
        return;
      }

      let message = `Upload failed (${xhr.status})`;
      let code: string | undefined;
      try {
        const body = JSON.parse(xhr.responseText) as {
          error?: { message?: string; code?: string };
        };
        message = body.error?.message ?? message;
        code = body.error?.code;
      } catch {
        // Non-JSON error body — keep default message.
      }
      reject(new ApiClientError(message, xhr.status, code));
    });

    xhr.addEventListener("error", () => {
      reject(new ApiClientError("Cover image upload failed.", 0));
    });

    xhr.open(
      "POST",
      `${coverUploadBaseUrl()}${API_PREFIX}/events/${eventId}/cover-image`,
    );
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.send(formData);
  });
}

export function deleteEventCoverImage(
  token: string,
  eventId: string,
): Promise<EventSummary> {
  return apiFetch<EventSummary>(`/events/${eventId}/cover-image`, {
    method: "DELETE",
    token,
  });
}
