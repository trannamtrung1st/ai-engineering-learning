import type { Page } from "@playwright/test";
import { loginAcademicAdmin } from "./academic-admin.js";
import { API_BASE_URL } from "./constants.js";
import { LECTURER_PERSONA } from "./fixtures.js";

/** Authenticate AcademicAdmin for PG-12 policy routes. */
export async function loginAcademicAdminPolicies(
  page: Page,
  afterLoginPath = "/admin/policies",
): Promise<void> {
  await loginAcademicAdmin(page, afterLoginPath);
}

/** Find an open session whose roster has at least one Present and one Late row. */
export async function findOpenSessionWithPresentAndLate(
  page: Page,
): Promise<{ sessionId: string; presentCode: string; lateCode: string } | null> {
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email: LECTURER_PERSONA.email, password: LECTURER_PERSONA.password },
  });
  const token = ((await login.json()) as { data?: { accessToken?: string } }).data?.accessToken;
  if (!token) return null;

  const sessions = (
    (await (
      await page.request.get(`${API_BASE_URL}/class-sessions?page=1&pageSize=50`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as { data?: { classSessionId: string; state: string }[] }
  ).data?.filter((s) => s.state === "Open");

  for (const session of sessions ?? []) {
    const roster = (
      (await (
        await page.request.get(
          `${API_BASE_URL}/class-sessions/${session.classSessionId}/attendance`,
          { headers: { Authorization: `Bearer ${token}` } },
        )
      ).json()) as {
        data?: {
          rows: { studentCode: string; attendanceStatus: string }[];
        };
      }
    ).data;
    const present = roster?.rows.find((r) => r.attendanceStatus === "Present");
    const late = roster?.rows.find((r) => r.attendanceStatus === "Late");
    if (present && late) {
      return {
        sessionId: session.classSessionId,
        presentCode: present.studentCode,
        lateCode: late.studentCode,
      };
    }
  }

  return null;
}

/** Find an open session with any Late attendance rows (policy-window driven). */
export async function findOpenSessionWithLateRows(
  page: Page,
): Promise<{ sessionId: string; lateCode: string } | null> {
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email: LECTURER_PERSONA.email, password: LECTURER_PERSONA.password },
  });
  const token = ((await login.json()) as { data?: { accessToken?: string } }).data?.accessToken;
  if (!token) return null;

  const sessions = (
    (await (
      await page.request.get(`${API_BASE_URL}/class-sessions?page=1&pageSize=50`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as { data?: { classSessionId: string; state: string }[] }
  ).data?.filter((s) => s.state === "Open");

  for (const session of sessions ?? []) {
    const roster = (
      (await (
        await page.request.get(
          `${API_BASE_URL}/class-sessions/${session.classSessionId}/attendance`,
          { headers: { Authorization: `Bearer ${token}` } },
        )
      ).json()) as {
        data?: { rows: { studentCode: string; attendanceStatus: string }[] };
      }
    ).data;
    const late = roster?.rows.find((r) => r.attendanceStatus === "Late");
    if (late) {
      return { sessionId: session.classSessionId, lateCode: late.studentCode };
    }
  }
  return null;
}

/** Find an open session with a pending student whose latest attempt matches a GPS outcome. */
export async function findOpenSessionWithPendingAttempt(
  page: Page,
  outcome: "GpsDisabled" | "GpsRequired" | "OutOfRadius",
): Promise<{ sessionId: string; studentCode: string } | null> {
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email: LECTURER_PERSONA.email, password: LECTURER_PERSONA.password },
  });
  const token = ((await login.json()) as { data?: { accessToken?: string } }).data?.accessToken;
  if (!token) return null;

  const sessions = (
    (await (
      await page.request.get(`${API_BASE_URL}/class-sessions?page=1&pageSize=100`, {
        headers: { Authorization: `Bearer ${token}` },
      })
    ).json()) as { data?: { classSessionId: string; state: string }[] }
  ).data?.filter((s) => s.state === "Open");

  for (const session of sessions ?? []) {
    const roster = (
      (await (
        await page.request.get(
          `${API_BASE_URL}/class-sessions/${session.classSessionId}/attendance`,
          { headers: { Authorization: `Bearer ${token}` } },
        )
      ).json()) as {
        data?: {
          rows: {
            studentCode: string;
            attendanceStatus: string;
            latestAttemptOutcome: string | null;
          }[];
        };
      }
    ).data;
    const row = roster?.rows.find(
      (candidate) =>
        candidate.attendanceStatus === "Pending" && candidate.latestAttemptOutcome === outcome,
    );
    if (row) {
      return { sessionId: session.classSessionId, studentCode: row.studentCode };
    }
  }
  return null;
}

/** Fetch rotating QR for an open session (lecturer auth). */
export async function fetchSessionQr(page: Page, sessionId: string): Promise<string> {
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email: LECTURER_PERSONA.email, password: LECTURER_PERSONA.password },
  });
  const token = ((await login.json()) as { data?: { accessToken?: string } }).data?.accessToken;
  if (!token) throw new Error("Lecturer login missing accessToken");

  const response = await page.request.get(
    `${API_BASE_URL}/class-sessions/${sessionId}/qr/current`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const payload = (
    (await response.json()) as { data?: { qrPayload?: string } }
  ).data?.qrPayload;
  if (!payload) throw new Error("QR response missing qrPayload");
  return payload;
}
