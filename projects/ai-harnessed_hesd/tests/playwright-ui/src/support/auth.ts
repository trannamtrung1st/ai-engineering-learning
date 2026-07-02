import type { Page } from "@playwright/test";
import { API_BASE_URL, DEFAULT_PASSWORD, WEB_BASE_URL } from "./constants.js";

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
  await page.goto(WEB_BASE_URL + afterLoginPath);
}
