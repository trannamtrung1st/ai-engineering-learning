/**
 * Traceability: FR-26 BR-17
 * TC-FR-26-003 TC-FR-26-014 TC-FR-26-015 TC-BR-17-003 TC-BR-17-012 TC-BR-17-013
 */
import { describe, expect, it } from "vitest";
import {
  computeUnexcusedAbsenceRate,
  exceedsAbsenceThreshold,
  resolveConfiguredAbsenceThreshold,
} from "./evaluator.js";
import type { AttendancePolicyRecord } from "../policy-engine/types.js";

describe("M10 absence-threshold evaluator — FR-26 BR-17", () => {
  it("TC-FR-26-003 TC-BR-17-003: excludes Excused from rate when excusedCountsTowardThreshold is false", () => {
    const statuses = [
      "Absent",
      "Absent",
      "Excused",
      "Excused",
      "Present",
      "Present",
      "Present",
      "Present",
      "Present",
      "Present",
    ] as const;

    const excluded = computeUnexcusedAbsenceRate([...statuses], false);
    expect(excluded.unexcusedAbsentCount).toBe(2);
    expect(excluded.eligibleSessionCount).toBe(8);
    expect(excluded.unexcusedAbsenceRate).toBe(25);

    const included = computeUnexcusedAbsenceRate([...statuses], true);
    expect(included.unexcusedAbsentCount).toBe(2);
    expect(included.eligibleSessionCount).toBe(10);
    expect(included.unexcusedAbsenceRate).toBe(20);
  });

  it("TC-FR-26-014 TC-BR-17-012: strict exceed — exactly at threshold does not alert", () => {
    expect(exceedsAbsenceThreshold(20, 20)).toBe(false);
    expect(exceedsAbsenceThreshold(20.01, 20)).toBe(true);
    expect(exceedsAbsenceThreshold(27.27, 20)).toBe(true);
  });

  it("TC-FR-26-015 TC-BR-17-013: null configured threshold when no policy overrides absenceThresholdPercent", () => {
    const policies: Partial<Record<"ClassSection" | "Institution", AttendancePolicyRecord>> = {
      Institution: {
        id: "p1",
        scopeType: "Institution",
        scopeId: null,
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
        autoCloseEnabled: true,
        absenceThresholdPercent: 30,
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
      },
    };

    expect(resolveConfiguredAbsenceThreshold(policies)).toBeNull();
  });

  it("TC-FR-26-002: section override wins over institution for configured threshold", () => {
    const policies: Partial<Record<"ClassSection" | "Institution", AttendancePolicyRecord>> = {
      Institution: {
        id: "p1",
        scopeType: "Institution",
        scopeId: null,
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
        autoCloseEnabled: true,
        absenceThresholdPercent: 30,
        excusedCountsTowardThreshold: false,
        manualEditWindowHours: 24,
        adminApprovalRequired: false,
        gpsRequired: false,
        gpsRadiusMeters: 100,
        gpsMinAccuracyMeters: null,
        effectiveFrom: null,
        effectiveTo: null,
        isActive: true,
        fieldOverrides: { absenceThresholdPercent: true },
        createdAt: new Date().toISOString(),
      },
      ClassSection: {
        id: "p2",
        scopeType: "ClassSection",
        scopeId: "section-1",
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
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
        fieldOverrides: { absenceThresholdPercent: true },
        createdAt: new Date().toISOString(),
      },
    };

    expect(resolveConfiguredAbsenceThreshold(policies)).toBe(20);
  });
});
