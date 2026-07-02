import { test } from "@playwright/test";

/**
 * Placeholder until browser-tester generates slice specs (NFR-24).
 * Keeps `npm run test:playwright-ui` from failing with "No tests found".
 */
test("playwright-ui workspace wiring smoke", async () => {
  // No browser navigation — verifies @playwright/test project loads only.
});
