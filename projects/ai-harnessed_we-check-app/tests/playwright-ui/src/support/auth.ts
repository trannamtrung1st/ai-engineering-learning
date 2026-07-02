import { expect, type Page } from "@playwright/test";
import {
  API_BASE_URL,
  DEFAULT_PASSWORD,
  PREVIEW_CREDENTIALS,
  WEB_BASE_URL,
} from "./constants.js";

export type DevRole = "student" | "instructor" | "admin";

const ROLE_HOMES: Record<DevRole, string> = {
  student: "/check-in",
  instructor: "/sessions",
  admin: "/admin/users",
};

/**
 * Dev login via API cookie injection — see docs/technical/10-local-development-setup.md
 */
export async function loginAs(
  page: Page,
  email: string,
  password: string = DEFAULT_PASSWORD,
  role: DevRole = "student",
): Promise<void> {
  const response = await page.request.post(`${API_BASE_URL}/auth/login`, {
    data: { email, password },
  });
  if (!response.ok()) {
    throw new Error(`Login failed for ${email}: ${response.status()}`);
  }
  await page.goto(WEB_BASE_URL + ROLE_HOMES[role]);
}

export async function loginAsStudent(
  page: Page,
  email?: string,
  password?: string,
): Promise<void> {
  const resolvedEmail = email ?? process.env.PLAYWRIGHT_STUDENT_EMAIL;
  if (!resolvedEmail) {
    throw new Error(
      "loginAsStudent requires email or PLAYWRIGHT_STUDENT_EMAIL env",
    );
  }
  await loginAs(page, resolvedEmail, password, "student");
}

export async function loginAsInstructor(
  page: Page,
  email?: string,
  password?: string,
): Promise<void> {
  const resolvedEmail = email ?? process.env.PLAYWRIGHT_INSTRUCTOR_EMAIL;
  if (!resolvedEmail) {
    throw new Error(
      "loginAsInstructor requires email or PLAYWRIGHT_INSTRUCTOR_EMAIL env",
    );
  }
  await loginAs(page, resolvedEmail, password, "instructor");
}

export async function loginAsAdmin(
  page: Page,
  email?: string,
  password: string = process.env.PLAYWRIGHT_ADMIN_PASSWORD ?? "AdminPass123",
): Promise<void> {
  const resolvedEmail = email ?? process.env.PLAYWRIGHT_ADMIN_EMAIL;
  if (!resolvedEmail) {
    throw new Error("loginAsAdmin requires email or PLAYWRIGHT_ADMIN_EMAIL env");
  }
  await loginAs(page, resolvedEmail, password, "admin");
}

/** Preview harness — restore fixtures when integration tests truncate auth tables */
export async function refreshPreviewFixtures(page: Page): Promise<void> {
  const res = await page.request.post(`${API_BASE_URL}/auth/preview/refresh-fixtures`);
  expect(res.status()).toBe(200);
}

/** UI login via LoginForm — preserves returnUrl when on /login?returnUrl=… */
export async function loginViaForm(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  await page.getByRole("textbox", { name: /email hoặc tên đăng nhập/i }).fill(email);
  await page.getByRole("textbox", { name: /mật khẩu/i }).fill(password);
  const loginResponse = page.waitForResponse(
    (res) => res.url().includes("/auth/login") && res.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^đăng nhập$/i }).click();
  const response = await loginResponse;
  if (response.ok()) {
    await page.waitForURL((url) => url.pathname !== "/login", { timeout: 15_000 });
  }
}

async function loginPreviewViaForm(
  page: Page,
  email: string,
  password: string,
): Promise<void> {
  if (!page.url().includes("/login")) {
    await page.goto(`${WEB_BASE_URL}/login`);
  }
  await loginViaForm(page, email, password);
  if (page.url().includes("/login")) {
    await refreshPreviewFixtures(page);
    await loginViaForm(page, email, password);
  }
  expect(page.url()).not.toMatch(/\/login$/);
}

export async function loginPreviewStudentViaForm(page: Page): Promise<void> {
  const { email, password } = PREVIEW_CREDENTIALS.student;
  await loginPreviewViaForm(page, email, password);
  await page.evaluate(() => {
    localStorage.setItem("wecheck-location-consent", "1");
    localStorage.setItem("wecheck-camera-consent", "1");
  });
}

export async function loginPreviewInstructorViaForm(page: Page): Promise<void> {
  const { email, password } = PREVIEW_CREDENTIALS.instructor;
  await loginPreviewViaForm(page, email, password);
}

export async function loginPreviewAdminViaForm(page: Page): Promise<void> {
  const { email, password } = PREVIEW_CREDENTIALS.admin;
  await loginPreviewViaForm(page, email, password);
}

/** Preview harness — backdate session for NFR-16 / AC-02c browser gates */
export async function previewExpireSession(page: Page): Promise<void> {
  const res = await page.request.post(`${API_BASE_URL}/auth/preview/expire-session`, {
    data: {},
  });
  expect(res.status()).toBe(200);

  const me = await page.request.get(`${API_BASE_URL}/auth/me`);
  expect(me.status()).toBe(401);
  const body = (await me.json()) as { errorCode?: string };
  expect(body.errorCode).toBe("SessionExpired");
}

/** Navigate after previewExpireSession — auth redirect may abort navigation. */
export async function gotoExpectingRedirect(
  page: Page,
  path: string,
  urlPattern: RegExp,
): Promise<void> {
  await page.goto(path).catch(() => {
    /* auth gate redirect during navigation */
  });
  await expect(page).toHaveURL(urlPattern, { timeout: 15_000 });
}

export async function assertUnauthenticated(page: Page): Promise<void> {
  const res = await page.request.get(`${API_BASE_URL}/auth/me`);
  expect(res.status()).toBe(401);
}

export async function logoutViaUserMenu(page: Page): Promise<void> {
  await page.getByTestId("user-menu-trigger").click();
  const logoutResponse = page.waitForResponse(
    (res) => res.url().includes("/auth/logout") && res.request().method() === "POST",
  );
  await page.getByTestId("user-menu-logout").click();
  const response = await logoutResponse;
  expect(response.status()).toBe(204);
  await page.waitForURL(/\/login$/);
}
