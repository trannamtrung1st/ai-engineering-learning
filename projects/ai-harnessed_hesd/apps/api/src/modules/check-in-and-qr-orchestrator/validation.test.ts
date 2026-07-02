/**
 * Traceability: FR-18 FR-22 BR-03 BR-07 AC-02 AC-08 FR-12 AC-03 FR-34
 */
import { describe, expect, it } from "vitest";
import {
  evaluateCheckInFailure,
  isResolvedAttendanceStatus,
  resolveAttendanceStatus,
} from "./validation.js";

describe("check-in validation order — FR-22 BR-03 BR-07", () => {
  const basePolicy = {
    presentWindowMinutes: 15,
    lateWindowMinutes: 15,
    gpsRequired: false,
    gpsRadiusMeters: 100,
    gpsMinAccuracyMeters: null,
  };

  it("TC-BR-03-006: session state precedes ExpiredQr", () => {
    expect(
      evaluateCheckInFailure({
        sessionState: "Scheduled",
        tokenFound: true,
        tokenExpired: true,
        enrolled: true,
        existingAttendanceStatus: null,
        policy: basePolicy,
        gps: undefined,
      }),
    ).toBe("SessionNotOpen");

    expect(
      evaluateCheckInFailure({
        sessionState: "Closed",
        tokenFound: true,
        tokenExpired: true,
        enrolled: true,
        existingAttendanceStatus: null,
        policy: basePolicy,
        gps: undefined,
      }),
    ).toBe("SessionClosed");
  });

  it("TC-BR-03-007: ExpiredQr precedes enrollment and duplicate checks", () => {
    expect(
      evaluateCheckInFailure({
        sessionState: "Open",
        tokenFound: true,
        tokenExpired: true,
        enrolled: false,
        existingAttendanceStatus: "Present",
        policy: basePolicy,
        gps: undefined,
      }),
    ).toBe("ExpiredQr");
  });

  it("TC-BR-07-009: DuplicateCheckIn precedes GPS checks", () => {
    expect(
      evaluateCheckInFailure({
        sessionState: "Open",
        tokenFound: true,
        tokenExpired: false,
        enrolled: true,
        existingAttendanceStatus: "Present",
        policy: { ...basePolicy, gpsRequired: true },
        gps: undefined,
      }),
    ).toBe("DuplicateCheckIn");
  });

  it("TC-BR-07-010: resolved attendance statuses block duplicate QR check-in", () => {
    for (const status of ["Present", "Late", "Manual Present", "Excused"]) {
      expect(isResolvedAttendanceStatus(status)).toBe(true);
      expect(
        evaluateCheckInFailure({
          sessionState: "Open",
          tokenFound: true,
          tokenExpired: false,
          enrolled: true,
          existingAttendanceStatus: status,
          policy: basePolicy,
          gps: undefined,
        }),
      ).toBe("DuplicateCheckIn");
    }
  });

  it("TC-FR-11-002: resolveAttendanceStatus assigns Present within window", () => {
    const openedAt = "2026-07-02T08:00:00.000Z";
    const checkInAt = new Date("2026-07-02T08:10:00.000Z");
    expect(resolveAttendanceStatus(openedAt, checkInAt, basePolicy)).toBe("Present");
    expect(resolveAttendanceStatus(openedAt, new Date("2026-07-02T08:20:00.000Z"), basePolicy)).toBe(
      "Late",
    );
  });
});
