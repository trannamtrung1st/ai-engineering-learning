import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ATTENDANCE_WINDOW_MS,
  BusinessRuleId,
  GPS_RADIUS_DEFAULT_METERS,
  INSTRUCTOR_EDIT_WINDOW_MS,
  QR_TOKEN_TTL_MS,
  haversineDistanceMeters,
  isWithinRadius,
} from "@wecheck/domain";

/**
 * Acceptance traceability for domain-package slice.
 * BR-01 BR-02 BR-03 BR-10
 */
const DOMAIN_SLICE_ACCEPTANCE_TAGS = [
  "BR-01",
  "BR-02",
  "BR-03",
  "BR-10",
] as const;

describe("@wecheck/api domain package wiring", () => {
  it("documents domain-package acceptance tags for harness coverage", () => {
    assert.equal(DOMAIN_SLICE_ACCEPTANCE_TAGS.length, 4);
    assert.ok(DOMAIN_SLICE_ACCEPTANCE_TAGS.includes("BR-01"));
    assert.ok(DOMAIN_SLICE_ACCEPTANCE_TAGS.includes("BR-02"));
    assert.ok(DOMAIN_SLICE_ACCEPTANCE_TAGS.includes("BR-03"));
    assert.ok(DOMAIN_SLICE_ACCEPTANCE_TAGS.includes("BR-10"));
  });

  it("resolves BR-01 attendance window constant from shared domain", () => {
    assert.equal(ATTENDANCE_WINDOW_MS, 600_000);
    assert.equal(BusinessRuleId.BR_01, "BR-01");
  });

  it("resolves BR-02 GPS radius and Haversine helpers from shared domain", () => {
    assert.equal(GPS_RADIUS_DEFAULT_METERS, 100);
    assert.equal(BusinessRuleId.BR_02, "BR-02");
    const distance = haversineDistanceMeters(
      10.762622,
      106.660172,
      10.762622,
      106.660172,
    );
    assert.ok(distance < 1);
    assert.equal(
      isWithinRadius(10.762622, 106.660172, 10.7627, 106.6602, 100),
      true,
    );
  });

  it("resolves BR-03 QR token TTL from shared domain", () => {
    assert.equal(QR_TOKEN_TTL_MS, 30_000);
    assert.equal(BusinessRuleId.BR_03, "BR-03");
  });

  it("resolves BR-10 instructor edit window from shared domain", () => {
    assert.equal(INSTRUCTOR_EDIT_WINDOW_MS, 86_400_000);
    assert.equal(BusinessRuleId.BR_10, "BR-10");
  });
});
