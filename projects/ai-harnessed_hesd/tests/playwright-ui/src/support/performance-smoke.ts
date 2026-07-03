import type { Page } from "@playwright/test";
import { execFile } from "node:child_process";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { API_BASE_URL, DEFAULT_PASSWORD, WEB_BASE_URL } from "./constants.js";
import { LECTURER_PERSONA, STUDENT_PERSONA } from "./fixtures.js";
import { fetchCurrentQr, loginLecturerToRoster } from "./roster.js";

export const IT_ADMIN_SEED_EMAIL = "e2e-itadmin@attendly.local";

const execFileAsync = promisify(execFile);
const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");

async function refreshPreviewScheduledSession(): Promise<void> {
  await execFileAsync("node", ["apps/api/scripts/preview-session-refresh.mjs"], {
    cwd: REPO_ROOT,
    env: process.env,
  });
}

interface LoginEnvelope {
  data?: { accessToken?: string };
}

interface ClassSessionSummary {
  classSessionId: string;
  state: string;
}

interface RosterCounts {
  present: number;
  late: number;
  pending: number;
  rejectedAttempts: number;
}

async function loginToken(page: Page, email: string): Promise<string> {
  const response = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email, password: DEFAULT_PASSWORD },
  });
  const body = (await response.json()) as LoginEnvelope;
  const token = body.data?.accessToken;
  if (!token) throw new Error(`Login failed for ${email}`);
  return token;
}

/** Open the first scheduled session and return its id. */
export async function openFreshScheduledSession(page: Page): Promise<string> {
  const lecturerToken = await loginToken(page, LECTURER_PERSONA.email);
  const list = await page.request.get(`${API_BASE_URL}/class-sessions?page=1&pageSize=50`, {
    headers: { Authorization: `Bearer ${lecturerToken}` },
  });
  const sessions = ((await list.json()) as { data?: ClassSessionSummary[] }).data ?? [];
  let scheduled = sessions.find((s) => s.state === "Scheduled");
  if (!scheduled) {
    await refreshPreviewScheduledSession();
    const retry = await page.request.get(`${API_BASE_URL}/class-sessions?page=1&pageSize=50`, {
      headers: { Authorization: `Bearer ${lecturerToken}` },
    });
    const retrySessions = ((await retry.json()) as { data?: ClassSessionSummary[] }).data ?? [];
    scheduled = retrySessions.find((s) => s.state === "Scheduled");
  }
  if (!scheduled) {
    throw new Error("No scheduled class session available for performance smoke");
  }

  await page.request.post(`${API_BASE_URL}/class-sessions/${scheduled.classSessionId}/open`, {
    headers: { Authorization: `Bearer ${lecturerToken}` },
    data: {},
  });

  return scheduled.classSessionId;
}

export async function fetchRosterCounts(
  page: Page,
  sessionId: string,
): Promise<RosterCounts> {
  const lecturerToken = await loginToken(page, LECTURER_PERSONA.email);
  const response = await page.request.get(
    `${API_BASE_URL}/class-sessions/${sessionId}/attendance`,
    { headers: { Authorization: `Bearer ${lecturerToken}` } },
  );
  const body = (await response.json()) as { data?: { counts: RosterCounts; rows: unknown[] } };
  if (!body.data) throw new Error("Roster fetch failed");
  return body.data.counts;
}

/** Mobile FLOW-01 journey with wall-clock timing from navigation to success UI. */
export async function runMobileCheckInJourney(
  page: Page,
  options: { sessionId: string; studentEmail?: string },
): Promise<{ elapsedMs: number; success: boolean }> {
  const email = options.studentEmail ?? STUDENT_PERSONA.email;
  const studentToken = await loginToken(page, email);
  const qrPayload = await fetchCurrentQr(page, options.sessionId);

  await page.setViewportSize(STUDENT_PERSONA.viewport);
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({
    latitude: 10.762622,
    longitude: 106.660172,
    accuracy: 10,
  });
  await page.addInitScript(
    ([key, token]) => {
      localStorage.setItem(key, token);
    },
    ["attendly.accessToken", studentToken] as const,
  );

  const start = Date.now();
  await page.goto(`${WEB_BASE_URL}/check-in?token=${qrPayload}`);

  const allow = page.getByRole("button", { name: "Cho phép vị trí" });
  if (await allow.isVisible().catch(() => false)) {
    await allow.click();
    await page.waitForTimeout(800);
  }

  const submit = page.getByRole("button", { name: "Xác nhận điểm danh" });
  if ((await submit.isVisible().catch(() => false)) && (await submit.isEnabled().catch(() => false))) {
    await submit.click();
  }

  let success = false;
  try {
    await page.getByRole("status").waitFor({ timeout: 20_000 });
    success = true;
  } catch {
    success = await page.getByRole("alert").isVisible().catch(() => false);
  }

  return { elapsedMs: Date.now() - start, success };
}

export async function loginItAdmin(page: Page, path = "/audit/logs"): Promise<void> {
  const token = await loginToken(page, IT_ADMIN_SEED_EMAIL);
  await page.setViewportSize(LECTURER_PERSONA.viewport);
  await page.addInitScript(
    ([key, value]) => {
      localStorage.setItem(key, value);
    },
    ["attendly.accessToken", token] as const,
  );
  await page.goto(`${WEB_BASE_URL}${path}`);
}

export { loginLecturerToRoster };
