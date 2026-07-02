import {
  API_BASE_URL,
  PREVIEW_CREDENTIALS,
} from "./src/support/constants.js";

/** Ensure preview login fixtures exist after integration test truncates (TC-FR-02-021). */
export default async function globalSetup(): Promise<void> {
  await fetch(`${API_BASE_URL}/auth/preview/refresh-fixtures`, {
    method: "POST",
  }).catch(() => undefined);

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    const res = await fetch(`${API_BASE_URL}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(PREVIEW_CREDENTIALS.student),
    });
    if (res.ok) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }

  throw new Error("Preview student fixture not ready for Playwright UI tests");
}
