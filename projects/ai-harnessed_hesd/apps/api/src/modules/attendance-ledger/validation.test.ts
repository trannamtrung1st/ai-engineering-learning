/**
 * Traceability: FR-09 FR-20 FR-21 BR-13 BR-14 BR-15 AC-12 AC-13 AC-14
 */
import { describe, expect, it } from "vitest";
import type { ActorContext } from "../identity/types.js";
import {
  isAdminOverrideRole,
  isAttendanceStatus,
  isCorrectableStatus,
  isSuccessfulAttendance,
  isWithinManualEditWindow,
  validateCorrectionPayload,
  validateCorrectionWindow,
} from "./validation.js";

const lecturerActor: ActorContext = {
  userId: "60000000-0000-4000-8000-000000000001",
  email: "lecturer@attendly.local",
  displayName: "Lecturer",
  roles: ["Lecturer"],
  assignments: [{ role: "Lecturer", scopeType: "ClassSection", scopeId: "section-1" }],
};

const adminActor: ActorContext = {
  userId: "60000000-0000-4000-8000-000000000005",
  email: "admin@attendly.local",
  displayName: "Admin",
  roles: ["AcademicAdmin"],
  assignments: [{ role: "AcademicAdmin", scopeType: "Institution", scopeId: null }],
};

describe("attendance-ledger validation — FR-20 FR-21 BR-14 AC-13", () => {
  it("TC-FR-20-013: rejects correction without required reason", () => {
    const result = validateCorrectionPayload({ status: "Manual Present", reason: "  " });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe("ReasonRequired");
    }
  });

  it("TC-FR-20-003: accepts allowed correction statuses", () => {
    expect(isCorrectableStatus("Manual Present")).toBe(true);
    expect(isCorrectableStatus("Excused")).toBe(true);
    expect(isCorrectableStatus("Pending")).toBe(false);
    expect(isAttendanceStatus("Absent")).toBe(true);
  });

  it("TC-BR-13-010: successful attendance statuses are guarded from absent downgrade", () => {
    expect(isSuccessfulAttendance("Present")).toBe(true);
    expect(isSuccessfulAttendance("Late")).toBe(true);
    expect(isSuccessfulAttendance("Manual Present")).toBe(true);
    expect(isSuccessfulAttendance("Pending")).toBe(false);
    expect(isSuccessfulAttendance("Absent")).toBe(false);
  });

  it("TC-FR-20-012: lecturer edit window expires after policy hours from close", () => {
    const closedAt = new Date("2026-07-02T10:00:00Z");
    const within = new Date("2026-07-02T20:00:00Z");
    const expired = new Date("2026-07-03T11:00:00Z");

    expect(isWithinManualEditWindow(closedAt, 24, within)).toBe(true);
    expect(isWithinManualEditWindow(closedAt, 24, expired)).toBe(false);

    const windowResult = validateCorrectionWindow({
      actor: lecturerActor,
      sessionState: "Closed",
      closedAt: closedAt.toISOString(),
      policy: { manualEditWindowHours: 24, reasonRequired: true },
      now: expired,
    });
    expect(windowResult.ok).toBe(false);
    if (!windowResult.ok) {
      expect(windowResult.error.code).toBe("EditWindowExpired");
    }
  });

  it("TC-FR-21-001: admin override bypasses lecturer edit window", () => {
    expect(isAdminOverrideRole(adminActor)).toBe(true);
    const result = validateCorrectionWindow({
      actor: adminActor,
      sessionState: "Closed",
      closedAt: "2026-07-01T10:00:00Z",
      policy: { manualEditWindowHours: 24, reasonRequired: true },
      now: new Date("2026-07-10T10:00:00Z"),
    });
    expect(result.ok).toBe(true);
  });

  it("TC-AC-13-008: lecturer may correct while session is Open", () => {
    const result = validateCorrectionWindow({
      actor: lecturerActor,
      sessionState: "Open",
      closedAt: null,
      policy: { manualEditWindowHours: 24, reasonRequired: true },
    });
    expect(result.ok).toBe(true);
  });
});
