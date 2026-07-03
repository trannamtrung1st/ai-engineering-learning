import type { Page } from "@playwright/test";
import { loginViaApi } from "./auth.js";
import { API_BASE_URL } from "./constants.js";
import { LECTURER_PERSONA, STUDENT_PERSONA } from "./fixtures.js";

interface LoginEnvelope {
  data?: { accessToken?: string };
}

interface ClassSessionSummary {
  classSessionId: string;
  state: string;
}

interface RosterRow {
  studentUserId: string;
  studentCode: string;
  attendanceStatus: string;
  latestAttemptOutcome: string | null;
}

interface RosterEnvelope {
  data?: {
    classSessionId: string;
    state: string;
    counts: { pending: number; rejectedAttempts: number };
    rows: RosterRow[];
  };
}

export interface RosterFixture {
  sessionId: string;
  state: string;
  row: RosterRow;
}

async function lecturerToken(page: Page): Promise<string> {
  const response = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email: LECTURER_PERSONA.email, password: LECTURER_PERSONA.password },
  });
  const body = (await response.json()) as LoginEnvelope;
  const token = body.data?.accessToken;
  if (!token) throw new Error("Lecturer login missing accessToken");
  return token;
}

async function listSessions(page: Page, token: string): Promise<ClassSessionSummary[]> {
  const response = await page.request.get(`${API_BASE_URL}/class-sessions?page=1&pageSize=50`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  const body = (await response.json()) as { data?: ClassSessionSummary[] };
  return body.data ?? [];
}

async function fetchRoster(
  page: Page,
  token: string,
  sessionId: string,
): Promise<RosterEnvelope["data"]> {
  const response = await page.request.get(
    `${API_BASE_URL}/class-sessions/${sessionId}/attendance`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = (await response.json()) as RosterEnvelope;
  return body.data ?? undefined;
}

export async function loginLecturerToRoster(page: Page, sessionId: string): Promise<void> {
  await page.setViewportSize(LECTURER_PERSONA.viewport);
  await loginViaApi(
    page,
    LECTURER_PERSONA.email,
    LECTURER_PERSONA.password,
    `/lecturer/sessions/${sessionId}/roster`,
  );
}

export async function findOpenSessionWithPending(page: Page): Promise<RosterFixture | null> {
  const token = await lecturerToken(page);
  for (const session of await listSessions(page, token)) {
    if (session.state !== "Open") continue;
    const roster = await fetchRoster(page, token, session.classSessionId);
    const pending = roster?.rows.find((row) => row.attendanceStatus === "Pending");
    if (pending) {
      return { sessionId: session.classSessionId, state: roster!.state, row: pending };
    }
  }
  return null;
}

export async function findClosedSessionWithAbsent(page: Page): Promise<RosterFixture | null> {
  const token = await lecturerToken(page);
  for (const session of await listSessions(page, token)) {
    if (session.state !== "Closed") continue;
    const roster = await fetchRoster(page, token, session.classSessionId);
    const absent = roster?.rows.find((row) => row.attendanceStatus === "Absent");
    if (absent) {
      return { sessionId: session.classSessionId, state: roster!.state, row: absent };
    }
  }
  return null;
}

export async function findOpenSessionWithRejectedAttempt(
  page: Page,
): Promise<RosterFixture | null> {
  const token = await lecturerToken(page);
  for (const session of await listSessions(page, token)) {
    if (session.state !== "Open") continue;
    const roster = await fetchRoster(page, token, session.classSessionId);
    const rejected = roster?.rows.find(
      (row) =>
        row.latestAttemptOutcome &&
        row.latestAttemptOutcome !== "Success" &&
        row.latestAttemptOutcome !== "GpsRequired",
    );
    if (rejected && (roster?.counts.rejectedAttempts ?? 0) > 0) {
      return { sessionId: session.classSessionId, state: roster!.state, row: rejected };
    }
  }
  return null;
}

export async function fetchCurrentQr(page: Page, sessionId: string): Promise<string> {
  const token = await lecturerToken(page);
  const response = await page.request.get(
    `${API_BASE_URL}/class-sessions/${sessionId}/qr/current`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = (await response.json()) as { data?: { qrPayload?: string } };
  const payload = body.data?.qrPayload;
  if (!payload) throw new Error("QR response missing qrPayload");
  return payload;
}

export async function submitStudentCheckIn(
  page: Page,
  options: {
    sessionId: string;
    studentEmail?: string;
    studentPassword?: string;
    gps?: { latitude: number; longitude: number; accuracyMeters: number };
  },
): Promise<void> {
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: {
      email: options.studentEmail ?? STUDENT_PERSONA.email,
      password: options.studentPassword ?? STUDENT_PERSONA.password,
    },
  });
  const token = ((await login.json()) as LoginEnvelope).data?.accessToken;
  if (!token) throw new Error("Student login missing accessToken");

  const qr = await fetchCurrentQr(page, options.sessionId);
  const body: Record<string, unknown> = { qrToken: qr };
  if (options.gps) body.gps = options.gps;

  await page.request.post(`${API_BASE_URL}/check-ins`, {
    headers: { Authorization: `Bearer ${token}` },
    data: body,
  });
}
