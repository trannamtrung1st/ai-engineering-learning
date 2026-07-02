/**
 * Traceability: FR-24
 * TC-FR-24-014
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_POLICIES_LIST_QUERY,
  parsePoliciesListQuery,
  policiesListQueryToSearchParams,
  sortPolicySummaries,
} from "./policies-list-query";
import type { PolicySummary } from "../api/policy-api";
import { buildDefaultScopeNameLookup } from "../api/policy-api";

describe("policies-list-query (FR-24)", () => {
  it("TC-FR-24-014: parses scopeLevel filter and pagination from URL", () => {
    const params = new URLSearchParams("scopeLevel=ClassSection&page=2&pageSize=25&sortOrder=desc");
    const query = parsePoliciesListQuery(params);
    expect(query.scopeLevel).toBe("ClassSection");
    expect(query.page).toBe(2);
    expect(query.pageSize).toBe(25);
    expect(query.sortOrder).toBe("desc");
  });

  it("round-trips default query state", () => {
    const roundTrip = parsePoliciesListQuery(
      policiesListQueryToSearchParams(DEFAULT_POLICIES_LIST_QUERY),
    );
    expect(roundTrip.page).toBe(1);
    expect(roundTrip.pageSize).toBe(25);
  });

  it("TC-FR-24-014: sortPolicySummaries flips row order when sortOrder toggles", () => {
    const lookup = buildDefaultScopeNameLookup();
    lookup.sections.set("50000000-0000-4000-8000-000000000001", "SE101-01");
    const policies: PolicySummary[] = [
      {
        id: "policy-old",
        scopeType: "ClassSection",
        scopeId: "50000000-0000-4000-8000-000000000001",
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 30,
        lateWindowMinutes: 15,
        autoCloseEnabled: true,
        absenceThresholdPercent: 20,
        excusedCountsTowardThreshold: false,
        manualEditWindowHours: 24,
        adminApprovalRequired: false,
        gpsRequired: true,
        gpsRadiusMeters: 100,
        gpsMinAccuracyMeters: null,
        effectiveFrom: null,
        effectiveTo: null,
        isActive: true,
        createdAt: "2026-07-02T20:09:27.591Z",
      },
      {
        id: "policy-new",
        scopeType: "ClassSection",
        scopeId: "50000000-0000-4000-8000-000000000001",
        checkInOpeningOffsetMinutes: null,
        presentWindowMinutes: 25,
        lateWindowMinutes: 10,
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
        createdAt: "2026-07-02T20:23:49.150Z",
      },
    ];

    const descFirst = sortPolicySummaries(policies, "desc", lookup)[0]?.id;
    const ascFirst = sortPolicySummaries(policies, "asc", lookup)[0]?.id;
    expect(descFirst).toBe("policy-new");
    expect(ascFirst).toBe("policy-old");
    expect(descFirst).not.toBe(ascFirst);
  });
});
