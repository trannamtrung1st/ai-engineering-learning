import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  evaluateSpoofHeuristics,
  SPOOF_ACCURACY_THRESHOLD_METERS,
} from "./spoof-heuristics.js";

/**
 * Traceability: AC-10 FR-10 BR-02
 * Cases: TC-FR-10-001 TC-FR-10-002 TC-AC-10-001 TC-AC-10-002
 */
describe("spoof heuristics (AC-10, FR-10)", () => {
  it("flags mockLocationDetected true (TC-FR-10-001, AC-10a)", () => {
    const result = evaluateSpoofHeuristics({
      mockLocationDetected: true,
      platform: "android",
    });
    assert.equal(result.spoofSuspected, true);
    assert.equal(result.spoofFlags?.mockLocationDetected, true);
  });

  it("flags abnormally perfect accuracy below threshold (TC-FR-10-002)", () => {
    const result = evaluateSpoofHeuristics({
      mockLocationDetected: false,
      accuracyMeters: 1.0,
      platform: "android",
    });
    assert.equal(result.spoofSuspected, true);
    assert.equal(result.spoofFlags?.accuracyMeters, 1.0);
  });

  it("allows normal accuracy at threshold (FR-10 negative path)", () => {
    const result = evaluateSpoofHeuristics({
      mockLocationDetected: false,
      accuracyMeters: SPOOF_ACCURACY_THRESHOLD_METERS,
      platform: "android",
    });
    assert.equal(result.spoofSuspected, false);
  });

  it("returns no spoof flags when metadata absent", () => {
    const result = evaluateSpoofHeuristics(undefined);
    assert.equal(result.spoofSuspected, false);
    assert.equal(result.spoofFlags, null);
  });
});
