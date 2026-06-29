import { describe, expect, it } from "vitest";
import {
  formatHistoryCheckInTime,
  formatHistorySessionDate,
} from "@/lib/history-format";

/** AC-14 / FR-14 — vi-VN history date formatting */
describe("history-format (AC-14, FR-14)", () => {
  it("formats session date in vi-VN locale", () => {
    const formatted = formatHistorySessionDate("2026-06-29T08:00:00.000Z");
    expect(formatted).toMatch(/29/);
    expect(formatted).toMatch(/06/);
    expect(formatted).toMatch(/2026/);
  });

  it("formats check-in time in vi-VN locale", () => {
    const formatted = formatHistoryCheckInTime("2026-06-29T08:05:00.000Z");
    expect(formatted).toMatch(/\d{1,2}:\d{2}/);
  });
});
