import { describe, expect, it } from "vitest";
import { resolveDuplicatePriorStatus } from "./duplicate-prior-status";

describe("resolveDuplicatePriorStatus (NFR-14)", () => {
  it("maps API duplicate details to badge and timestamp", () => {
    const prior = resolveDuplicatePriorStatus({
      attendanceStatus: "Present",
      checkInAt: "2026-07-02T08:02:11Z",
    });

    expect(prior).toEqual({
      attendanceStatus: "Present",
      timestamp: expect.stringMatching(/\d{2}:\d{2}/),
    });
  });

  it("returns null when duplicate details are incomplete", () => {
    expect(resolveDuplicatePriorStatus({ attendanceStatus: "Present" })).toBeNull();
    expect(resolveDuplicatePriorStatus({ checkInAt: "2026-07-02T08:02:11Z" })).toBeNull();
  });
});
