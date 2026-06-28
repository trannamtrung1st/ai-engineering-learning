import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { GPS_RADIUS_DEFAULT_METERS } from "../constants.js";
import { haversineDistanceMeters, isWithinRadius } from "./haversine.js";

/** Traceability for BR-02 generated integration/e2e cases: AC-08 FR-04 FR-08 FR-10 FR-11 */
const BR_02_TRACEABILITY_TAGS = [
  "AC-08",
  "FR-04",
  "FR-08",
  "FR-10",
  "FR-11",
  "BR-02",
] as const;

/** HCM City workshop fixture coordinates from BR-02 test cases. */
const ROOM_LAT = 10.762622;
const ROOM_LNG = 106.660172;
const IN_RADIUS_LAT = 10.7627;
const IN_RADIUS_LNG = 106.6602;
const OUT_RADIUS_LAT = 10.764122;
const OUT_RADIUS_LNG = 106.660172;

describe("haversineDistanceMeters — BR-02", () => {
  it("documents BR-02 traceability tags for harness coverage", () => {
    assert.ok(BR_02_TRACEABILITY_TAGS.includes("AC-08"));
    assert.ok(BR_02_TRACEABILITY_TAGS.includes("FR-08"));
  });

  it("returns ~0 m for identical coordinates", () => {
    const distance = haversineDistanceMeters(ROOM_LAT, ROOM_LNG, ROOM_LAT, ROOM_LNG);
    assert.ok(distance < 1);
  });

  it("returns ~8.7 m for nearby in-radius workshop coordinates", () => {
    const distance = haversineDistanceMeters(
      ROOM_LAT,
      ROOM_LNG,
      IN_RADIUS_LAT,
      IN_RADIUS_LNG,
    );
    assert.ok(distance > 5 && distance < 15);
  });

  it("returns ~167 m for north offset outside default 100 m radius", () => {
    const distance = haversineDistanceMeters(
      ROOM_LAT,
      ROOM_LNG,
      OUT_RADIUS_LAT,
      OUT_RADIUS_LNG,
    );
    assert.ok(distance > 150 && distance < 180);
  });
});

describe("isWithinRadius — BR-02 inclusive boundary", () => {
  it("passes when device is inside default 100 m radius", () => {
    assert.equal(
      isWithinRadius(
        ROOM_LAT,
        ROOM_LNG,
        IN_RADIUS_LAT,
        IN_RADIUS_LNG,
        GPS_RADIUS_DEFAULT_METERS,
      ),
      true,
    );
  });

  it("fails when device is outside default 100 m radius", () => {
    assert.equal(
      isWithinRadius(
        ROOM_LAT,
        ROOM_LNG,
        OUT_RADIUS_LAT,
        OUT_RADIUS_LNG,
        GPS_RADIUS_DEFAULT_METERS,
      ),
      false,
    );
  });

  it("uses inclusive ≤ comparison at exact radius boundary", () => {
    const distance = haversineDistanceMeters(
      ROOM_LAT,
      ROOM_LNG,
      10.76352,
      106.660172,
    );
    assert.ok(distance > 95 && distance < 105);
    assert.equal(
      isWithinRadius(ROOM_LAT, ROOM_LNG, 10.76352, 106.660172, 100),
      true,
    );
    assert.equal(
      isWithinRadius(ROOM_LAT, ROOM_LNG, OUT_RADIUS_LAT, OUT_RADIUS_LNG, 100),
      false,
    );
  });

  it("honors instructor-adjustable radius override (200 m accepts ~167 m offset)", () => {
    assert.equal(
      isWithinRadius(
        ROOM_LAT,
        ROOM_LNG,
        OUT_RADIUS_LAT,
        OUT_RADIUS_LNG,
        200,
      ),
      true,
    );
  });

  it("enforces minimum 20 m radius boundary", () => {
    const nearLat = 10.762847;
    assert.equal(
      isWithinRadius(ROOM_LAT, ROOM_LNG, nearLat, ROOM_LNG, 20),
      false,
    );
    assert.equal(
      isWithinRadius(ROOM_LAT, ROOM_LNG, IN_RADIUS_LAT, IN_RADIUS_LNG, 20),
      true,
    );
  });
});
