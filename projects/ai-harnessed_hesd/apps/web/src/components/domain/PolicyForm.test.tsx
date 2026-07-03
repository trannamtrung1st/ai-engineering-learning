/**
 * Traceability: FR-24 FR-25
 * TC-FR-24-015 TC-FR-24-013
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PolicyForm } from "./PolicyForm";

vi.mock("../../lib/api/policy-api", () => ({
  createPolicy: vi.fn(),
  updatePolicy: vi.fn(),
  fetchEffectivePolicy: vi.fn(),
}));

vi.mock("../../lib/api/academic-api", () => ({
  fetchCourses: vi.fn(),
  fetchClassSections: vi.fn(),
}));

import { createPolicy, fetchEffectivePolicy } from "../../lib/api/policy-api";
import { fetchClassSections, fetchCourses } from "../../lib/api/academic-api";
import { SEED_FACULTY_ID } from "../../lib/api/seed-fixtures";

describe("PolicyForm (FR-24 FR-25)", () => {
  beforeEach(() => {
    vi.mocked(fetchCourses).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "30000000-0000-4000-8000-000000000001",
          code: "SE101",
          name: "Nhập môn",
          facultyId: "10000000-0000-4000-8000-000000000001",
          creditUnits: 3,
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 100, totalItems: 1, totalPages: 1 },
    });
    vi.mocked(fetchClassSections).mockResolvedValue({
      ok: true,
      items: [
        {
          id: "50000000-0000-4000-8000-000000000001",
          sectionCode: "SE101-01",
          termId: "20000000-0000-4000-8000-000000000001",
          courseId: "30000000-0000-4000-8000-000000000001",
          lecturerUserId: "60000000-0000-4000-8000-000000000001",
          defaultRoomId: null,
          capacity: 40,
          isActive: true,
        },
      ],
      pagination: { page: 1, pageSize: 100, totalItems: 1, totalPages: 1 },
    });
    vi.mocked(fetchEffectivePolicy).mockResolvedValue({
      ok: true,
      data: {
        values: {
          presentWindowMinutes: 15,
          lateWindowMinutes: 15,
          manualEditWindowHours: 24,
          gpsRequired: false,
          gpsRadiusMeters: 100,
        },
        sources: {
          presentWindowMinutes: "Institution",
          lateWindowMinutes: "Institution",
          manualEditWindowHours: "Institution",
          gpsRequired: "Institution",
          gpsRadiusMeters: "Institution",
        },
      },
    });
  });

  it("TC-FR-24-013: GPS radius input disabled when gpsRequired is off", async () => {
    render(<PolicyForm mode="create" />);
    await waitFor(() => {
      expect(screen.getByTestId("gps-radius-input")).toBeDisabled();
    });
  });

  it("TC-FR-24-015: toggling GPS required enables radius field", async () => {
    render(<PolicyForm mode="create" />);
    await waitFor(() => expect(screen.getByTestId("gps-radius-input")).toBeDisabled());

    fireEvent.click(screen.getByRole("switch", { name: "Bắt buộc GPS" }));
    expect(screen.getByTestId("gps-radius-input")).not.toBeDisabled();
  });

  it("TC-FR-24-015: submits faculty policy with matching scopeId after scope switch", async () => {
    vi.mocked(createPolicy).mockResolvedValue({
      ok: true,
      data: {
        id: "policy-faculty",
        scopeType: "Faculty",
        scopeId: SEED_FACULTY_ID,
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 15,
        lateWindowMinutes: 15,
        autoCloseEnabled: true,
        absenceThresholdPercent: 20,
        excusedCountsTowardThreshold: false,
        manualEditWindowHours: 24,
        adminApprovalRequired: false,
        gpsRequired: false,
        gpsRadiusMeters: null,
        gpsMinAccuracyMeters: null,
        effectiveFrom: null,
        effectiveTo: null,
        isActive: true,
        createdAt: "2026-07-02T12:00:00Z",
      },
    });

    render(<PolicyForm mode="create" />);
    await waitFor(() => screen.getByTestId("policy-form"));

    fireEvent.click(screen.getByRole("radio", { name: "Khoa" }));
    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Khoa" })).toHaveValue(SEED_FACULTY_ID);
    });
    fireEvent.click(screen.getByRole("button", { name: "Lưu chính sách" }));

    await waitFor(() => {
      expect(createPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          scopeType: "Faculty",
          scopeId: SEED_FACULTY_ID,
        }),
      );
    });
  });

  it("TC-FR-24-015: submits class-section policy with GPS fields", async () => {
    vi.mocked(createPolicy).mockResolvedValue({
      ok: true,
      data: {
        id: "policy-1",
        scopeType: "ClassSection",
        scopeId: "50000000-0000-4000-8000-000000000001",
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 20,
        lateWindowMinutes: 15,
        autoCloseEnabled: true,
        absenceThresholdPercent: 20,
        excusedCountsTowardThreshold: false,
        manualEditWindowHours: 48,
        adminApprovalRequired: false,
        gpsRequired: true,
        gpsRadiusMeters: 100,
        gpsMinAccuracyMeters: null,
        effectiveFrom: null,
        effectiveTo: null,
        isActive: true,
        createdAt: "2026-07-02T12:00:00Z",
      },
    });

    render(<PolicyForm mode="create" />);
    await waitFor(() => screen.getByTestId("policy-form"));

    fireEvent.change(screen.getByTestId("present-window-input"), { target: { value: "20" } });
    fireEvent.change(screen.getByTestId("manual-edit-window-input"), {
      target: { value: "48" },
    });
    fireEvent.click(screen.getByRole("switch", { name: "Bắt buộc GPS" }));
    fireEvent.click(screen.getByRole("button", { name: "Lưu chính sách" }));

    await waitFor(() => {
      expect(createPolicy).toHaveBeenCalledWith(
        expect.objectContaining({
          scopeType: "ClassSection",
          presentWindowMinutes: 20,
          manualEditWindowHours: 48,
          gpsRequired: true,
          gpsRadiusMeters: 100,
        }),
      );
    });
  });
});
