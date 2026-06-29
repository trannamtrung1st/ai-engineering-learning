import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  computeAbsenceRate,
  exceedsAbsenceThreshold,
  DEFAULT_ABSENCE_THRESHOLD_PERCENT,
} from "./absence-threshold.js";

/**
 * Traceability: AC-16 FR-16 BR-05
 * Unit: TC-AC-16-011 TC-AC-16-018 TC-FR-16-009 TC-FR-16-016 TC-BR-05-009 TC-BR-05-016
 */
describe("absence threshold logic (AC-16, FR-16, BR-05)", () => {
  it("TC-AC-16-011: computeAbsenceRate returns fraction for valid session count", () => {
    const result = computeAbsenceRate({
      unexcusedAbsenceCount: 2,
      sessionCount: 5,
    });
    assert.equal(result.absenceRate, 0.4);
    assert.equal(result.unexcusedAbsenceCount, 2);
    assert.equal(result.sessionCount, 5);
  });

  it("TC-AC-16-011: zero session count yields absenceRate 0", () => {
    const result = computeAbsenceRate({
      unexcusedAbsenceCount: 0,
      sessionCount: 0,
    });
    assert.equal(result.absenceRate, 0);
  });

  it("TC-BR-05-009: exactly 20% does not exceed default threshold", () => {
    assert.equal(exceedsAbsenceThreshold(0.2, DEFAULT_ABSENCE_THRESHOLD_PERCENT), false);
  });

  it("TC-BR-05-009: rate above 20% exceeds default threshold", () => {
    assert.equal(exceedsAbsenceThreshold(0.21, DEFAULT_ABSENCE_THRESHOLD_PERCENT), true);
    assert.equal(exceedsAbsenceThreshold(0.25, DEFAULT_ABSENCE_THRESHOLD_PERCENT), true);
  });

  it("TC-FR-16-017: custom admin threshold applied in comparison", () => {
    assert.equal(exceedsAbsenceThreshold(0.2, 25), false);
    assert.equal(exceedsAbsenceThreshold(0.2, 15), true);
  });

  it("TC-AC-16-004: excused-only numerator yields below-threshold rate", () => {
    const result = computeAbsenceRate({
      unexcusedAbsenceCount: 1,
      sessionCount: 6,
    });
    assert.equal(result.absenceRate, 1 / 6);
    assert.equal(exceedsAbsenceThreshold(result.absenceRate, 20), false);
  });
});
