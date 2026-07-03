import type { Page } from "@playwright/test";
import { API_BASE_URL } from "./constants.js";
import { loginViaApi } from "./auth.js";
import { LECTURER_PERSONA, STUDENT_PERSONA } from "./fixtures.js";

interface QrCurrentEnvelope {
  data?: { qrPayload?: string; classSessionId?: string };
}

interface LoginEnvelope {
  data?: { accessToken?: string };
}

/** Fetch rotating QR payload for a class session (lecturer auth). */
export async function fetchCurrentQrToken(
  page: Page,
  classSessionId: string,
): Promise<string> {
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: {
      email: LECTURER_PERSONA.email,
      password: LECTURER_PERSONA.password,
    },
  });
  if (!login.ok()) {
    throw new Error(`Lecturer login failed: ${login.status()}`);
  }
  const { data } = (await login.json()) as LoginEnvelope;
  const accessToken = data?.accessToken;
  if (!accessToken) {
    throw new Error("Lecturer login missing accessToken");
  }

  const qr = await page.request.get(
    `${API_BASE_URL}/class-sessions/${classSessionId}/qr/current`,
    { headers: { Authorization: `Bearer ${accessToken}` } },
  );
  if (!qr.ok()) {
    throw new Error(`QR fetch failed: ${qr.status()}`);
  }
  const body = (await qr.json()) as QrCurrentEnvelope;
  const payload = body.data?.qrPayload;
  if (!payload) {
    throw new Error("QR response missing qrPayload");
  }
  return payload;
}

/** Open a scheduled seed session and return its first QR payload. */
export async function openSeedSessionAndFetchQr(page: Page): Promise<{
  classSessionId: string;
  qrPayload: string;
}> {
  const classSessionId = "70000000-0000-4000-8000-000000000001";
  const login = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: {
      email: LECTURER_PERSONA.email,
      password: LECTURER_PERSONA.password,
    },
  });
  const { data } = (await login.json()) as LoginEnvelope;
  const accessToken = data?.accessToken;
  if (!accessToken) {
    throw new Error("Lecturer login missing accessToken");
  }

  await page.request.post(`${API_BASE_URL}/class-sessions/${classSessionId}/open`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    data: {},
  });

  const qrPayload = await fetchCurrentQrToken(page, classSessionId);
  return { classSessionId, qrPayload };
}

/** Authenticate student for mobile PG-02 flows. */
export async function loginStudentMobile(page: Page): Promise<void> {
  await page.setViewportSize(STUDENT_PERSONA.viewport);
  await loginViaApi(
    page,
    STUDENT_PERSONA.email,
    STUDENT_PERSONA.password,
    "/check-in",
  );
}

export async function expectButtonMinSize(
  locator: import("@playwright/test").Locator,
  minSize: number,
): Promise<void> {
  const box = await locator.boundingBox();
  if (!box) {
    throw new Error("Button has no bounding box");
  }
  if (box.width < minSize || box.height < minSize) {
    throw new Error(
      `Touch target ${box.width}x${box.height} below ${minSize}px minimum`,
    );
  }
}
