/**
 * Traceability: FR-24 FR-25 FR-35 BR-20 AC-09 AC-10
 * TC-FR-25-002 TC-BR-20-002 TC-FR-35-001 TC-FR-24-012 TC-FR-24-013
 */
import { describe, expect, it } from "vitest";
import { INSTITUTION_POLICY_DEFAULTS } from "./defaults.js";
import { flattenResolvedPolicy, resolveEffectivePolicyFromRows } from "./resolver.js";
import type { AttendancePolicyRecord } from "./types.js";
import {
  evaluateGpsDistance,
  evaluateGpsPayload,
  haversineMeters,
  isWithinManualEditWindow,
  resolveAttendanceStatus,
  validateAbsenceThreshold,
  validateGpsFields,
  validatePolicyCreateInput,
  validatePolicyWindows,
} from "./validation.js";

function policyRow(
  scopeType: AttendancePolicyRecord["scopeType"],
  scopeId: string | null,
  overrides: Partial<AttendancePolicyRecord>,
): AttendancePolicyRecord {
  return {
    id: `${scopeType}-policy`,
    scopeType,
    scopeId,
    checkInOpeningOffsetMinutes: null,
    presentWindowMinutes: 10,
    lateWindowMinutes: 10,
    autoCloseEnabled: true,
    absenceThresholdPercent: 20,
    excusedCountsTowardThreshold: false,
    manualEditWindowHours: 24,
    adminApprovalRequired: false,
    gpsRequired: false,
    gpsRadiusMeters: 100,
    gpsMinAccuracyMeters: null,
    effectiveFrom: null,
    effectiveTo: null,
    isActive: true,
    fieldOverrides: { presentWindowMinutes: true },
    createdAt: new Date().toISOString(),
    ...overrides,
  };
}

describe("M06 policy engine validation — FR-24 FR-35 BR-20", () => {
  it("TC-FR-24-012: rejects contradictory windows and out-of-range absence threshold", () => {
    expect(validatePolicyWindows(30, -1)?.code).toBe("InvalidPayload");
    expect(validateAbsenceThreshold(150)?.code).toBe("InvalidPayload");
    expect(validatePolicyCreateInput({
      scopeType: "ClassSection",
      scopeId: "50000000-0000-4000-8000-000000000001",
      presentWindowMinutes: 15,
      lateWindowMinutes: 15,
      manualEditWindowHours: 48,
      absenceThresholdPercent: 150,
      gpsRequired: false,
    })?.code).toBe("InvalidPayload");
  });

  it("TC-FR-24-013: rejects gpsRadius when gpsRequired is false or non-positive", () => {
    expect(validateGpsFields(false, 100, null)?.code).toBe("InvalidPayload");
    expect(validateGpsFields(true, 0, null)?.code).toBe("InvalidPayload");
    expect(validateGpsFields(true, 100, null)).toBeNull();
  });

  it("TC-FR-35-001 TC-AC-09-007: GPS payload outcomes for required policy", () => {
    const policy = { gpsRequired: true, gpsMinAccuracyMeters: 50 };
    expect(evaluateGpsPayload(null, policy)).toBe("GpsRequired");
    expect(evaluateGpsPayload({ latitude: 10, longitude: 106, accuracyMeters: 10, permissionDenied: true }, policy)).toBe(
      "GpsDisabled",
    );
    expect(evaluateGpsPayload({ latitude: 10, longitude: 106, accuracyMeters: 120 }, policy)).toBe("LowAccuracy");
    expect(evaluateGpsPayload({ latitude: 10, longitude: 106, accuracyMeters: 20 }, policy)).toBeNull();
  });

  it("TC-FR-35-011 TC-AC-10-007: haversine boundary around 100m radius", () => {
    const room = { latitude: 10.762622, longitude: 106.660172 };
    const nearLat = 10.76352;
    const farLat = 10.76372;
    const nearDistance = haversineMeters(nearLat, 106.660172, room.latitude, room.longitude);
    const farDistance = haversineMeters(farLat, 106.660172, room.latitude, room.longitude);
    expect(evaluateGpsDistance({ latitude: nearLat, longitude: 106.660172, accuracyMeters: 10 }, room, 100).outcome).toBeNull();
    expect(
      evaluateGpsDistance({ latitude: farLat, longitude: 106.660172, accuracyMeters: 10 }, room, 100).outcome,
    ).toBe("OutOfRadius");
    expect(nearDistance).toBeLessThan(100);
    expect(farDistance).toBeGreaterThan(100);
  });

  it("TC-FR-25-002 TC-BR-20-002: per-field precedence section > course > faculty > institution", () => {
    const resolved = resolveEffectivePolicyFromRows({
      Institution: policyRow("Institution", null, {
        presentWindowMinutes: 10,
        lateWindowMinutes: 10,
        manualEditWindowHours: 24,
        gpsRequired: false,
        fieldOverrides: { presentWindowMinutes: true, lateWindowMinutes: true, manualEditWindowHours: true, gpsRequired: true },
      }),
      Faculty: policyRow("Faculty", "faculty-1", {
        presentWindowMinutes: 12,
        fieldOverrides: { presentWindowMinutes: true },
      }),
      Course: policyRow("Course", "course-1", {
        lateWindowMinutes: 18,
        gpsRequired: true,
        gpsRadiusMeters: 120,
        fieldOverrides: { lateWindowMinutes: true, gpsRequired: true, gpsRadiusMeters: true },
      }),
      ClassSection: policyRow("ClassSection", "section-1", {
        presentWindowMinutes: 20,
        fieldOverrides: { presentWindowMinutes: true },
      }),
    });

    const flat = flattenResolvedPolicy(resolved);
    expect(flat.presentWindowMinutes).toBe(20);
    expect(resolved.presentWindowMinutes.source).toBe("ClassSection");
    expect(flat.lateWindowMinutes).toBe(18);
    expect(resolved.lateWindowMinutes.source).toBe("Course");
    expect(flat.gpsRequired).toBe(true);
    expect(flat.gpsRadiusMeters).toBe(120);
    expect(flat.manualEditWindowHours).toBe(24);
    expect(resolved.manualEditWindowHours.source).toBe("Institution");
  });

  it("TC-BR-20-004: manual edit window helper respects policy hours", () => {
    const closedAt = new Date("2026-07-02T10:00:00.000Z");
    expect(isWithinManualEditWindow(closedAt, 72, new Date("2026-07-04T10:00:00.000Z"))).toBe(true);
    expect(isWithinManualEditWindow(closedAt, 72, new Date("2026-07-05T11:00:00.000Z"))).toBe(false);
  });

  it("TC-FR-25-005: resolveAttendanceStatus uses present window from policy", () => {
    const openedAt = "2026-07-02T08:00:00.000Z";
    expect(
      resolveAttendanceStatus(openedAt, new Date("2026-07-02T08:12:00.000Z"), {
        presentWindowMinutes: 25,
        lateWindowMinutes: 15,
      }),
    ).toBe("Present");
    expect(
      resolveAttendanceStatus(openedAt, new Date("2026-07-02T08:30:00.000Z"), {
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
      }),
    ).toBe("Late");
    expect(INSTITUTION_POLICY_DEFAULTS.presentWindowMinutes).toBe(15);
  });
});
