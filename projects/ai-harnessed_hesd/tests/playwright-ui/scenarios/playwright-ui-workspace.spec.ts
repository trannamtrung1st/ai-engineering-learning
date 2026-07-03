import { test, expect } from "@playwright/test";
import { API_BASE_URL } from "../src/support/constants.js";
import {
  LECTURER_PERSONA,
  NARROW_MOBILE_VIEWPORT,
  STUDENT_PERSONA,
} from "../src/support/fixtures.js";

/**
 * Slice: playwright-ui-workspace
 * Source: AC-01, AC-11, AC-16, NFR-14 — workspace smoke wiring before feature slices codegen flows.
 */
test.describe("playwright-ui-workspace", () => {
  test("@AC-01 lecturer desktop smoke loads Attendly shell", async ({ page }) => {
    await page.setViewportSize(LECTURER_PERSONA.viewport);
    await page.goto("/");
    await expect(page).toHaveURL(/\/showcase$/);
    await expect(
      page.getByRole("heading", { name: /Attendly Design System/i }),
    ).toBeVisible();
    await expect(page.getByText("Attendly", { exact: true }).first()).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Danh sách buổi học/i }),
    ).toBeVisible();
  });

  test("@AC-11 @NFR-14 student mobile smoke loads mobile-ready shell", async ({
    page,
  }) => {
    await page.setViewportSize(STUDENT_PERSONA.viewport);
    await page.goto("/");
    await expect(page).toHaveURL(/\/showcase$/);
    await expect(
      page.getByRole("heading", { name: /Attendly Design System/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Kết quả điểm danh trên mobile/i }),
    ).toBeVisible();
  });

  test("@AC-16 preview API health is reachable for regression wiring", async ({
    request,
  }) => {
    const response = await request.get(`${API_BASE_URL}/health`);
    expect(response.ok()).toBeTruthy();
    const body = (await response.json()) as { status?: string; db?: string };
    expect(body.status).toBe("ok");
    expect(body.db).toBe("connected");
  });

  test("TC-NFR-14-008 @NFR-14 narrow mobile viewport keeps shell readable without overflow", async ({
    page,
  }) => {
    await page.setViewportSize(NARROW_MOBILE_VIEWPORT);
    await page.goto("/");
    await expect(page).toHaveURL(/\/showcase$/);
    await expect(
      page.getByRole("heading", { name: /Attendly Design System/i }),
    ).toBeVisible();
    const hasHorizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );
    expect(hasHorizontalOverflow).toBe(false);
  });
});
