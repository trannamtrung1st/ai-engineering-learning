import type { Page } from "@playwright/test";
import { API_BASE_URL, DEFAULT_PASSWORD, WEB_BASE_URL } from "./constants.js";

/** Clear client auth session before each browser scenario. */
export async function clearWebSession(page: Page): Promise<void> {
  await page.goto(`${WEB_BASE_URL}/login`);
  await page.evaluate(() => {
    localStorage.removeItem("accessToken");
    localStorage.removeItem("roles");
  });
}

/**
 * Dev login via API — customize endpoint, cookies, and post-login route per product.
 * See docs/technical/10-local-development-setup.md
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

  const body = (await response.json()) as {
    data: { accessToken: string; roles: string[] };
  };

  // localStorage is origin-scoped — seed session on the web app origin before routing
  await page.goto(`${WEB_BASE_URL}/login`);
  await page.evaluate(
    ({ token, roles }) => {
      localStorage.setItem("accessToken", token);
      localStorage.setItem("roles", JSON.stringify(roles));
    },
    {
      token: body.data.accessToken,
      roles: body.data.roles,
    },
  );

  await page.goto(WEB_BASE_URL + afterLoginPath);
}
