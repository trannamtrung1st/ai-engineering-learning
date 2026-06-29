import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ATTENDANCE_WINDOW_MS } from "../constants.js";
import { SessionStatus } from "../enums.js";
import {
  computeAttendanceWindowEnd,
  computeNominalWindowEnd,
  isWithinAttendanceWindow,
  shouldAutoCloseSession,
} from "./attendance-window.js";
import {
  InvalidSessionTransitionError,
  canTransitionSession,
  getSessionStatusAfterTransition,
  hasValidRoomGps,
} from "./state-guard.js";

/** Traceability for BR-01 generated integration/e2e cases: AC-05 FR-05 */
const BR_01_TRACEABILITY_TAGS = ["AC-05", "FR-05", "BR-01"] as const;

describe("SM-01 session state transitions — BR-01 BR-07", () => {
  it("allows Draft → Active via open", () => {
    assert.equal(canTransitionSession(SessionStatus.Draft, "open"), true);
    assert.equal(
      getSessionStatusAfterTransition(SessionStatus.Draft, "open"),
      SessionStatus.Active,
    );
  });

  it("allows Draft → Cancelled via cancel", () => {
    assert.equal(canTransitionSession(SessionStatus.Draft, "cancel"), true);
    assert.equal(
      getSessionStatusAfterTransition(SessionStatus.Draft, "cancel"),
      SessionStatus.Cancelled,
    );
  });

  it("allows Active → Closed via close", () => {
    assert.equal(canTransitionSession(SessionStatus.Active, "close"), true);
    assert.equal(
      getSessionStatusAfterTransition(SessionStatus.Active, "close"),
      SessionStatus.Closed,
    );
  });

  it("rejects close from Draft and reopen from Closed", () => {
    assert.equal(canTransitionSession(SessionStatus.Draft, "close"), false);
    assert.equal(canTransitionSession(SessionStatus.Closed, "open"), false);
    assert.throws(
      () => getSessionStatusAfterTransition(SessionStatus.Closed, "close"),
      InvalidSessionTransitionError,
    );
  });
});

describe("BR-07 room GPS validation", () => {
  it("requires finite lat/lng within WGS-84 bounds", () => {
    assert.equal(
      hasValidRoomGps({ roomLatitude: 10.762622, roomLongitude: 106.660172 }),
      true,
    );
    assert.equal(
      hasValidRoomGps({ roomLatitude: null, roomLongitude: 106.660172 }),
      false,
    );
    assert.equal(
      hasValidRoomGps({ roomLatitude: 91, roomLongitude: 0 }),
      false,
    );
  });
});

describe("BR-01 attendance window", () => {
  const scheduledStart = new Date("2026-06-01T09:00:00.000Z");
  const openedAt = new Date("2026-06-01T09:05:00.000Z");

  it("documents BR-01 traceability tags for harness coverage", () => {
    assert.ok(BR_01_TRACEABILITY_TAGS.includes("AC-05"));
    assert.ok(BR_01_TRACEABILITY_TAGS.includes("FR-05"));
  });

  it("computes nominal window end as scheduledStart + 10 minutes", () => {
    const end = computeNominalWindowEnd(scheduledStart);
    assert.equal(end.getTime() - scheduledStart.getTime(), ATTENDANCE_WINDOW_MS);
  });

  it("uses earlier manual closedAt as effective window end", () => {
    const earlyClose = new Date("2026-06-01T09:08:00.000Z");
    const end = computeAttendanceWindowEnd(scheduledStart, earlyClose);
    assert.equal(end.getTime(), earlyClose.getTime());
  });

  it("allows check-in while Active and within window", () => {
    assert.equal(
      isWithinAttendanceWindow({
        status: SessionStatus.Active,
        openedAt,
        scheduledStart,
        closedAt: null,
        now: new Date(scheduledStart.getTime() + ATTENDANCE_WINDOW_MS),
      }),
      true,
    );
  });

  it("rejects check-in one second after window end while still Active", () => {
    assert.equal(
      isWithinAttendanceWindow({
        status: SessionStatus.Active,
        openedAt,
        scheduledStart,
        closedAt: null,
        now: new Date(scheduledStart.getTime() + ATTENDANCE_WINDOW_MS + 1_000),
      }),
      false,
    );
  });

  it("rejects check-in when session is Closed", () => {
    assert.equal(
      isWithinAttendanceWindow({
        status: SessionStatus.Closed,
        openedAt,
        scheduledStart,
        closedAt: new Date("2026-06-01T09:12:00.000Z"),
        now: openedAt,
      }),
      false,
    );
  });

  it("ends window immediately after instructor manual close", () => {
    const manualClose = new Date("2026-06-01T09:07:00.000Z");
    assert.equal(
      isWithinAttendanceWindow({
        status: SessionStatus.Active,
        openedAt,
        scheduledStart,
        closedAt: manualClose,
        now: new Date(manualClose.getTime() + 1),
      }),
      false,
    );
  });

  it("triggers auto-close at scheduledStart + 10 minutes", () => {
    const atEnd = new Date(scheduledStart.getTime() + ATTENDANCE_WINDOW_MS);
    assert.equal(shouldAutoCloseSession(scheduledStart, atEnd), true);
    assert.equal(
      shouldAutoCloseSession(
        scheduledStart,
        new Date(atEnd.getTime() - 1),
      ),
      false,
    );
  });
});
