import type {
  CertificateEligibilityState,
  EventState,
  RegistrationState,
} from "@we-event/domain";

import { apiFetch } from "@/lib/api-client";

export interface PaginatedResult<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
}

export interface EventListItem {
  eventId: string;
  name: string;
  state: EventState;
  startAt: string;
  location: string;
  coverImageUrl?: string;
}

export interface MyRegistrationListItem {
  registrationId: string;
  eventId: string;
  eventName: string;
  eventState: EventState;
  state: RegistrationState;
  updatedAt: string;
  waitlistPosition: number | null;
  reasonText: string | null;
  checkinOpenAt: string;
  checkinCloseAt: string;
  feedbackOpenAt: string;
  feedbackCloseAt: string;
  selfCheckinEnabled?: boolean;
}

export interface FetchEventsParams {
  page?: number;
  pageSize?: number;
  q?: string;
  state?: EventState;
  sort?: string;
}

export interface FetchMyRegistrationsParams {
  page?: number;
  pageSize?: number;
  state?: RegistrationState;
  sort?: string;
}

export interface EventRuleConfig {
  capacity: number;
  waitlistEnabled: boolean;
  registrationOpenAt: string;
  registrationCloseAt: string;
  checkinOpenAt: string;
  checkinCloseAt: string;
  feedbackRequired: boolean;
  feedbackOpenAt: string;
  feedbackCloseAt: string;
  registrationPaused: boolean;
  selfCheckinEnabled?: boolean;
  version: number;
}

export interface EventSummary {
  eventId: string;
  organizationId: string;
  name: string;
  description: string;
  location: string;
  state: EventState;
  startAt: string;
  endAt: string;
  version: number;
  updatedAt: string;
  coverImageUrl?: string;
  ruleConfig: EventRuleConfig;
}

export interface RegistrationStatus {
  registrationId: string;
  eventId: string;
  participantId: string;
  state: RegistrationState;
  reasonCode: string | null;
  reasonText: string | null;
  waitlistPosition: number | null;
  requestedAt: string;
  updatedAt: string;
  version: number;
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

export interface FeedbackResult {
  feedbackId: string;
  eventId: string;
  registrationId: string;
  participantId: string;
  submittedAt: string;
  answers: Record<string, unknown>;
}

export interface EligibilityResult {
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
}

export interface SessionInfo {
  actorId: string;
  role: string;
  assignedEventIds: string[];
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

export function fetchSession(token: string): Promise<SessionInfo> {
  return apiFetch<SessionInfo>("/me", { token });
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

export function fetchEvents(
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

export function fetchEvent(token: string, eventId: string): Promise<EventSummary> {
  return apiFetch<EventSummary>(`/events/${eventId}`, { token });
}

export function fetchRegistrationStatus(
  token: string,
  eventId: string,
): Promise<{ registration: RegistrationStatus | null }> {
  return apiFetch<{ registration: RegistrationStatus | null }>(
    `/events/${eventId}/registration-status`,
    { token },
  );
}

export function registerForEvent(
  token: string,
  eventId: string,
): Promise<RegistrationStatus> {
  return apiFetch<RegistrationStatus>(
    `/events/${eventId}/registrations`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify({}),
      headers: { "Idempotency-Key": idempotencyKey() },
    }),
  );
}

export function cancelRegistration(
  token: string,
  eventId: string,
  registrationId: string,
): Promise<{
  cancelled: RegistrationStatus;
  promoted: RegistrationStatus | null;
}> {
  return apiFetch(
    `/events/${eventId}/registrations/${registrationId}/cancel`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify({}),
      headers: { "Idempotency-Key": idempotencyKey() },
    }),
  );
}

export function selfCheckin(token: string, eventId: string): Promise<CheckinResult> {
  return apiFetch<CheckinResult>(
    `/events/${eventId}/self-checkin`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify({}),
      headers: { "Idempotency-Key": idempotencyKey() },
    }),
  );
}

export function submitFeedback(
  token: string,
  eventId: string,
  input: { registrationId?: string; answers: Record<string, unknown> },
): Promise<FeedbackResult> {
  return apiFetch<FeedbackResult>(
    `/events/${eventId}/feedback`,
    authInit(token, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  );
}

export function fetchMyEligibility(
  token: string,
  eventId: string,
): Promise<EligibilityResult> {
  return apiFetch<EligibilityResult>(`/events/${eventId}/eligibility/me`, { token });
}

export interface DevTokenResponse {
  token: string;
  sub: string;
  role: string;
}

export function requestDevToken(sub: string): Promise<DevTokenResponse> {
  return apiFetch<DevTokenResponse>("/dev/token", {
    method: "POST",
    body: JSON.stringify({ sub, role: "Participant" }),
    headers: { "Content-Type": "application/json" },
  });
}

export function fetchMyRegistrations(
  token: string,
  params: FetchMyRegistrationsParams = {},
): Promise<PaginatedResult<MyRegistrationListItem>> {
  const query = buildQueryString({
    page: params.page,
    pageSize: params.pageSize,
    state: params.state,
    sort: params.sort,
  });
  return apiFetch<PaginatedResult<MyRegistrationListItem>>(
    `/me/registrations${query}`,
    { token },
  );
}
