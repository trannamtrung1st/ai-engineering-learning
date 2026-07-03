import type { Page } from "@playwright/test";
import { API_BASE_URL, DEFAULT_PASSWORD, WEB_BASE_URL } from "./constants.js";
import type { SmokePersona } from "./fixtures.js";

const ACCESS_TOKEN_STORAGE_KEY = "attendly.accessToken";

interface LoginEnvelope {
  data?: { accessToken?: string };
}

/**
 * Dev login via API — see docs/technical/10-local-development-setup.md and POST /v1/auth/login.
 * Persists accessToken in localStorage for upcoming auth-aware UI routes.
 */
export async function loginViaApi(
  page: Page,
  email: string,
  password: string = DEFAULT_PASSWORD,
  afterLoginPath: string = "/",
): Promise<void> {
  const response = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email, password },
  });
  if (!response.ok()) {
    throw new Error(`Login failed for ${email}: ${response.status()}`);
  }

  const body = (await response.json()) as LoginEnvelope;
  const accessToken = body.data?.accessToken;
  if (accessToken) {
    await page.addInitScript(
      ([key, token]) => {
        localStorage.setItem(key, token);
      },
      [ACCESS_TOKEN_STORAGE_KEY, accessToken] as const,
    );
  }

  await page.goto(WEB_BASE_URL + afterLoginPath);
}

/** Convenience wrapper for seed-aligned smoke personas. */
export async function loginAsPersona(
  page: Page,
  persona: SmokePersona,
): Promise<void> {
  await loginViaApi(page, persona.email, persona.password, persona.homePath);
}
