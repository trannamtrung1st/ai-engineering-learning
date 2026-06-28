import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  GPS_RADIUS_DEFAULT_METERS,
  GPS_RADIUS_MAX_METERS,
  SessionStatus,
  hasValidRoomGps,
  canTransitionSession,
} from "@wecheck/domain";
import {
  normalizeCreateSession,
  validateCreateSession,
  validatePatchSession,
} from "./validation.js";

/** Traceability: AC-04 AC-05 FR-04 FR-05 BR-01 BR-07 */
const SESSION_TRACEABILITY_TAGS = [
  "AC-04",
  "AC-05",
  "FR-04",
  "FR-05",
  "BR-01",
  "BR-07",
] as const;

describe("session-management state guard and validation (AC-04, FR-04, BR-07)", () => {
  it("documents session slice traceability tags", () => {
    assert.ok(SESSION_TRACEABILITY_TAGS.includes("AC-04"));
    assert.ok(SESSION_TRACEABILITY_TAGS.includes("BR-07"));
  });

  it("allows Draft lifecycle transitions per SM-01", () => {
    assert.equal(canTransitionSession(SessionStatus.Draft, "open"), true);
    assert.equal(canTransitionSession(SessionStatus.Draft, "cancel"), true);
    assert.equal(canTransitionSession(SessionStatus.Active, "close"), true);
    assert.equal(canTransitionSession(SessionStatus.Draft, "close"), false);
  });

  it("hasValidRoomGps rejects partial coordinates (BR-07)", () => {
    assert.equal(
      hasValidRoomGps({ roomLatitude: 10.762622, roomLongitude: null }),
      false,
    );
    assert.equal(
      hasValidRoomGps({ roomLatitude: null, roomLongitude: 106.660172 }),
      false,
    );
    assert.equal(
      hasValidRoomGps({ roomLatitude: 10.762622, roomLongitude: 106.660172 }),
      true,
    );
  });

  it("validateCreateSession rejects out-of-range latitude (TC-AC-04-012)", () => {
    const errors = validateCreateSession({
      classId: "10000000-0000-4000-8000-000000000101",
      subjectId: "20000000-0000-4000-8000-000000000201",
      title: "Workshop",
      roomName: "Phòng A201",
      roomLatitude: 91,
      roomLongitude: 106.660172,
      scheduledStart: "2026-07-01T08:00:00.000Z",
    });
    assert.ok(errors.some((e) => e.field === "roomLatitude"));
  });

  it("validateCreateSession rejects gpsRadiusMeters below 20 (TC-AC-04-013)", () => {
    const errors = validateCreateSession({
      classId: "10000000-0000-4000-8000-000000000101",
      subjectId: "20000000-0000-4000-8000-000000000201",
      title: "Workshop",
      roomName: "Phòng A201",
      roomLatitude: 10.762622,
      roomLongitude: 106.660172,
      gpsRadiusMeters: 10,
      scheduledStart: "2026-07-01T08:00:00.000Z",
    });
    assert.ok(errors.some((e) => e.field === "gpsRadiusMeters"));
  });

  it("normalizeCreateSession applies default 100 m radius (TC-FR-04-028)", () => {
    const normalized = normalizeCreateSession({
      classId: "10000000-0000-4000-8000-000000000101",
      subjectId: "20000000-0000-4000-8000-000000000201",
      title: "Workshop",
      roomName: "Phòng A201",
      scheduledStart: "2026-07-01T08:00:00.000Z",
    });
    assert.equal(normalized.gpsRadiusMeters, GPS_RADIUS_DEFAULT_METERS);
  });

  it("validatePatchSession accepts GPS coordinate updates on Draft", () => {
    const errors = validatePatchSession({
      roomLatitude: 10.762622,
      roomLongitude: 106.660172,
    });
    assert.equal(errors.length, 0);
  });

  it("validateCreateSession accepts radius within 20–500 m bounds", () => {
    const errors = validateCreateSession({
      classId: "10000000-0000-4000-8000-000000000101",
      subjectId: "20000000-0000-4000-8000-000000000201",
      title: "Workshop",
      roomName: "Phòng A201",
      roomLatitude: 10.762622,
      roomLongitude: 106.660172,
      gpsRadiusMeters: GPS_RADIUS_MAX_METERS,
      scheduledStart: "2026-07-01T08:00:00.000Z",
    });
    assert.equal(errors.length, 0);
  });
});
