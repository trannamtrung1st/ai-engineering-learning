/**
 * Traceability: FR-07 FR-08 BR-01 BR-02 AC-01 AC-05
 * TC-FR-07-005 TC-FR-08-005 TC-AC-01-003
 */
import { describe, expect, it } from "vitest";
import {
  sessionCheckInGate,
  validateCloseTransition,
  validateOpenTransition,
} from "./validation.js";

describe("session lifecycle validation — FR-07 FR-08 BR-01 BR-02", () => {
  it("TC-FR-07-005 TC-AC-01-003: only Scheduled may transition to Open", () => {
    expect(validateOpenTransition("Scheduled")).toEqual({ allowed: true });
    expect(validateOpenTransition("Open")).toEqual({
      allowed: false,
      code: "InvalidSessionTransition",
      fromState: "Open",
    });
    expect(validateOpenTransition("Closed")).toEqual({
      allowed: false,
      code: "InvalidSessionTransition",
      fromState: "Closed",
    });
    expect(validateOpenTransition("Cancelled")).toEqual({
      allowed: false,
      code: "InvalidSessionTransition",
      fromState: "Cancelled",
    });
  });

  it("TC-FR-08-005: only Open transitions to Closed; Closed is idempotent", () => {
    expect(validateCloseTransition("Open")).toEqual({ allowed: true, idempotent: false });
    expect(validateCloseTransition("Closed")).toEqual({ allowed: true, idempotent: true });
    expect(validateCloseTransition("Scheduled")).toEqual({
      allowed: false,
      code: "InvalidSessionTransition",
      fromState: "Scheduled",
    });
    expect(validateCloseTransition("Cancelled")).toEqual({
      allowed: false,
      code: "InvalidSessionTransition",
      fromState: "Cancelled",
    });
  });

  it("BR-01 BR-02: check-in gate short-circuits on session state", () => {
    expect(sessionCheckInGate("Open")).toBe("Open");
    expect(sessionCheckInGate("Scheduled")).toBe("SessionNotOpen");
    expect(sessionCheckInGate("Cancelled")).toBe("SessionNotOpen");
    expect(sessionCheckInGate("Closed")).toBe("SessionClosed");
  });
});
