import type { Page } from "@playwright/test";
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
  studentCode: string;
  attendanceStatus: string;
  latestAttemptOutcome: string | null;
}

interface RosterEnvelope {
  data?: {
    classSessionId: string;
    state: string;
    counts: {
      pending: number;
      absent: number;
      rejectedAttempts: number;
    };
    rows: RosterRow[];
  };
}

/** Deterministic stale QR token rejected as ExpiredQr in preview seed. */
export const STALE_QR_TOKEN = "611776e0-10c5-48fb-9a2b-7162f02dd5f7";

export async function loginToken(
  page: Page,
  email: string,
  password: string = LECTURER_PERSONA.password,
): Promise<string> {
  const response = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email, password },
  });
  const body = (await response.json()) as LoginEnvelope;
  const token = body.data?.accessToken;
  if (!token) throw new Error(`Login missing accessToken for ${email}`);
  return token;
}

export async function seedAuth(page: Page, token: string): Promise<void> {
  await page.addInitScript(([key, value]) => {
    localStorage.setItem(key, value);
  }, ["attendly.accessToken", token] as const);
}

export async function listSessions(
  page: Page,
  token: string,
): Promise<ClassSessionSummary[]> {
  const response = await page.request.get(
    `${API_BASE_URL}/class-sessions?page=1&pageSize=50`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = (await response.json()) as { data?: ClassSessionSummary[] };
  return body.data ?? [];
}

export async function fetchRoster(
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

export async function fetchCurrentQr(
  page: Page,
  token: string,
  sessionId: string,
): Promise<string> {
  const response = await page.request.get(
    `${API_BASE_URL}/class-sessions/${sessionId}/qr/current`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const body = (await response.json()) as { data?: { qrPayload?: string } };
  const payload = body.data?.qrPayload;
  if (!payload) throw new Error("QR response missing qrPayload");
  return payload;
}

export async function findOpenSessionWithPending(
  page: Page,
  token: string,
): Promise<{ sessionId: string; pendingCount: number } | null> {
  for (const session of await listSessions(page, token)) {
    if (session.state !== "Open") continue;
    const roster = await fetchRoster(page, token, session.classSessionId);
    if ((roster?.counts.pending ?? 0) > 0) {
      return {
        sessionId: session.classSessionId,
        pendingCount: roster!.counts.pending,
      };
    }
  }
  return null;
}

export async function findOpenSessionWithPresentAndPending(
  page: Page,
  token: string,
): Promise<{ sessionId: string } | null> {
  for (const session of await listSessions(page, token)) {
    if (session.state !== "Open") continue;
    const roster = await fetchRoster(page, token, session.classSessionId);
    const hasPresent = roster?.rows.some((row) =>
      ["Present", "Late", "Manual Present"].includes(row.attendanceStatus),
    );
    const hasPending = (roster?.counts.pending ?? 0) > 0;
    if (hasPresent && hasPending) {
      return { sessionId: session.classSessionId };
    }
  }
  return null;
}

export async function ensureStudentCheckedIn(
  page: Page,
  options: {
    lecturerToken: string;
    studentToken: string;
    sessionId: string;
    studentCode?: string;
  },
): Promise<void> {
  const roster = await fetchRoster(page, options.lecturerToken, options.sessionId);
  const studentCode = options.studentCode ?? "SV001";
  const row = roster?.rows.find((r) => r.studentCode === studentCode);
  if (
    row &&
    ["Present", "Late", "Manual Present"].includes(row.attendanceStatus)
  ) {
    return;
  }
  const qr = await fetchCurrentQr(page, options.lecturerToken, options.sessionId);
  await page.request.post(`${API_BASE_URL}/check-ins`, {
    headers: { Authorization: `Bearer ${options.studentToken}` },
    data: {
      qrToken: qr,
      gps: { latitude: 10.762622, longitude: 106.660172, accuracyMeters: 10 },
    },
  });
}

export async function prepareStudentMobile(
  page: Page,
  accessToken?: string,
): Promise<void> {
  const token =
    accessToken ??
    (await loginToken(page, STUDENT_PERSONA.email, STUDENT_PERSONA.password));
  await page.setViewportSize(STUDENT_PERSONA.viewport);
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({
    latitude: 10.762622,
    longitude: 106.660172,
    accuracy: 10,
  });
  await seedAuth(page, token);
}
