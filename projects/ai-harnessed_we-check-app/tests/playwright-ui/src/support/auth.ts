import type { Page } from "@playwright/test";
import { API_BASE_URL, DEFAULT_PASSWORD, WEB_BASE_URL } from "./constants.js";

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
