/**
 * AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-03 — threshold gate unit tests.
 */
import { describe, expect, it } from "vitest";
import {
  PERFORMANCE_SMOKE_THRESHOLDS,
  computeMedian,
  evaluateMajorityCompletionGate,
  evaluateMedianLatencyGate,
  evaluateSuccessRateGate,
  isWithinCompletionWindow,
} from "./thresholds.js";

describe("performance smoke thresholds — AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-03", () => {
  it("TC-AC-20-006: median latency gate fails at or above 30 seconds", () => {
    const passVerdict = evaluateMedianLatencyGate([100, 200, 500, 800]);
    expect(passVerdict.pass).toBe(true);
    expect(passVerdict.actual).toBeLessThan(PERFORMANCE_SMOKE_THRESHOLDS.medianCheckInMs);

    const failVerdict = evaluateMedianLatencyGate([29_000, 30_000, 31_000]);
    expect(failVerdict.pass).toBe(false);
    expect(failVerdict.actual).toBeGreaterThanOrEqual(PERFORMANCE_SMOKE_THRESHOLDS.medianCheckInMs);
  });

  it("TC-AC-22-007: success rate gate fails below 99%", () => {
    const passVerdict = evaluateSuccessRateGate(995, 1000);
    expect(passVerdict.pass).toBe(true);

    const failVerdict = evaluateSuccessRateGate(988, 1000);
    expect(failVerdict.pass).toBe(false);
    expect(failVerdict.actual).toBeLessThan(PERFORMANCE_SMOKE_THRESHOLDS.validSuccessRateMin);
  });

  it("TC-AC-21-007: majority completion gate fails at or below 50%", () => {
    const passVerdict = evaluateMajorityCompletionGate(26, 50);
    expect(passVerdict.pass).toBe(true);

    const failVerdict = evaluateMajorityCompletionGate(25, 50);
    expect(failVerdict.pass).toBe(false);
  });

  it("computeMedian handles even and odd sample sizes", () => {
    expect(computeMedian([1, 3, 5])).toBe(3);
    expect(computeMedian([1, 2, 3, 4])).toBe(2.5);
    expect(computeMedian([])).toBe(0);
  });

  it("isWithinCompletionWindow respects AC-21 five-minute window", () => {
    const openedAt = new Date("2026-07-02T10:00:00.000Z");
    expect(isWithinCompletionWindow(new Date("2026-07-02T10:04:59.000Z"), openedAt)).toBe(true);
    expect(isWithinCompletionWindow(new Date("2026-07-02T10:05:01.000Z"), openedAt)).toBe(false);
  });
});
