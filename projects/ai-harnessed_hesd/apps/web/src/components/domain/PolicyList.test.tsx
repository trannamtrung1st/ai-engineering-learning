/**
 * Traceability: FR-24
 * TC-FR-24-014
 */
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PolicyList } from "./PolicyList";

vi.mock("../../lib/api/policy-api", () => ({
  fetchPolicies: vi.fn(),
  ensurePolicyListRegressionFixtures: vi.fn().mockResolvedValue(undefined),
  buildDefaultScopeNameLookup: vi.fn(() => ({
    faculties: new Map(),
    courses: new Map(),
    sections: new Map([["50000000-0000-4000-8000-000000000001", "SE101-01"]]),
  })),
  resolvePolicyScopeName: vi.fn(() => "SE101-01"),
}));

vi.mock("../../lib/api/academic-api", () => ({
  fetchCourses: vi.fn(),
  fetchClassSections: vi.fn(),
}));

import { fetchPolicies } from "../../lib/api/policy-api";
import { fetchClassSections, fetchCourses } from "../../lib/api/academic-api";

describe("PolicyList (FR-24)", () => {
  beforeEach(() => {
    vi.mocked(fetchCourses).mockResolvedValue({
      ok: true,
      items: [],
      pagination: { page: 1, pageSize: 100, totalItems: 0, totalPages: 0 },
    });
    vi.mocked(fetchClassSections).mockResolvedValue({
      ok: true,
      items: [],
      pagination: { page: 1, pageSize: 100, totalItems: 0, totalPages: 0 },
    });
    vi.mocked(fetchPolicies).mockResolvedValue({
      ok: true,
      items: [
        {
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
      ],
      pagination: { page: 1, pageSize: 25, totalItems: 1, totalPages: 1 },
    });
  });

  it("TC-FR-24-014: renders policy table with toolbar and pagination meta", async () => {
    render(
      <MemoryRouter>
        <PolicyList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("table-toolbar")).toBeInTheDocument();
      expect(screen.getByText(/Hiển thị 1–1 \/ 1 chính sách/)).toBeInTheDocument();
    });
  });

  it("TC-FR-24-014: renders removable scopeLevel filter chip when scoped", async () => {
    render(
      <MemoryRouter initialEntries={["/?scopeLevel=ClassSection"]}>
        <PolicyList />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByRole("group", { name: "Bộ lọc đang áp dụng" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /Gỡ Cấp phạm vi: Lớp học phần/ })).toBeInTheDocument();
    });
  });
});
