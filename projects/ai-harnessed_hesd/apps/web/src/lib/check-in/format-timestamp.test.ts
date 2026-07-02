import { describe, expect, it } from "vitest";
import { formatCheckInTimestamp } from "./format-timestamp";

describe("formatCheckInTimestamp (FR-23 AC-11)", () => {
  it("formats ISO UTC check-in time for mobile display", () => {
    const formatted = formatCheckInTimestamp("2026-07-02T08:02:11Z", "en-GB");
    expect(formatted).toMatch(/^\d{2}:\d{2}$/);
  });
});
