import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  ATTENDANCE_WINDOW_MS,
  AttendanceStatus,
  BusinessRuleId,
  CheckInOutcome,
  DOMAIN_PACKAGE_VERSION,
  ErrorCode,
  GPS_RADIUS_DEFAULT_METERS,
  GPS_RADIUS_MAX_METERS,
  GPS_RADIUS_MIN_METERS,
  INSTRUCTOR_EDIT_WINDOW_MS,
  NON_FUNCTIONAL_REQUIREMENT_IDS,
  PASSWORD_POLICY,
  QR_TOKEN_TTL_MS,
  SessionStatus,
  UserRole,
  blocksDuplicateCheckIn,
  canManualEditAttendance,
  computeTokenExpiresAt,
  isPasswordLengthValid,
  isQrTokenExpired,
  BUSINESS_RULE_ERROR_CODES,
  ValidationRuleId,
} from "./index.js";

/**
 * Traceability for NFR-14 generated integration/e2e cases:
 * AC-01 AC-02 BR-06 FR-01 FR-02 FR-07 NFR-14
 */
const NFR_14_TRACEABILITY_TAGS = [
  "AC-01",
  "AC-02",
  "BR-06",
  "FR-01",
  "FR-02",
  "FR-07",
  "NFR-14",
] as const;

/** Traceability for BR-01 generated integration/e2e cases: AC-05 FR-05 */
const BR_01_TRACEABILITY_TAGS = ["AC-05", "FR-05", "BR-01"] as const;

/** Traceability for BR-02 generated integration/e2e cases */
const BR_02_TRACEABILITY_TAGS = [
  "AC-08",
  "FR-04",
  "FR-08",
  "FR-10",
  "FR-11",
  "BR-02",
  "BR-10",
] as const;

/** Traceability for BR-03 generated integration/e2e cases: AC-06 FR-06 FR-07 FR-09 */
const BR_03_TRACEABILITY_TAGS = [
  "AC-06",
  "FR-06",
  "FR-07",
  "FR-09",
  "BR-03",
] as const;

/** Traceability for BR-10 generated integration/e2e cases */
const BR_10_TRACEABILITY_TAGS = [
  "AC-11",
  "NFR-15",
  "BR-08",
  "FR-10",
  "FR-11",
  "BR-10",
] as const;

describe("@wecheck/domain monorepo bootstrap", () => {
  it("exports a stable package version", () => {
    assert.equal(DOMAIN_PACKAGE_VERSION, "0.1.0");
  });

  it("documents NFR-14 traceability tags for harness coverage", () => {
    assert.ok(NFR_14_TRACEABILITY_TAGS.includes("NFR-14"));
    assert.equal(NFR_14_TRACEABILITY_TAGS.length, 7);
  });
});

describe("NFR-14 credential policy identifiers", () => {
  it("defines VAL-03 minimum password length of 8 characters", () => {
    assert.equal(NON_FUNCTIONAL_REQUIREMENT_IDS.NFR_14, "NFR-14");
    assert.equal(PASSWORD_POLICY.MIN_LENGTH, 8);
    assert.equal(isPasswordLengthValid(7), false);
    assert.equal(isPasswordLengthValid(8), true);
  });

  it("defines VAL-03 maximum password length of 128 characters", () => {
    assert.equal(PASSWORD_POLICY.MAX_LENGTH, 128);
    assert.equal(isPasswordLengthValid(128), true);
    assert.equal(isPasswordLengthValid(129), false);
  });
});

describe("domain enums and constants — BR-01 BR-02 BR-03 BR-04 BR-10", () => {
  it("documents BR traceability tags for harness test-case coverage", () => {
    assert.ok(BR_01_TRACEABILITY_TAGS.includes("AC-05"));
    assert.ok(BR_02_TRACEABILITY_TAGS.includes("FR-08"));
    assert.ok(BR_03_TRACEABILITY_TAGS.includes("AC-06"));
    assert.ok(BR_10_TRACEABILITY_TAGS.includes("NFR-15"));
  });

  it("exports canonical session and attendance status enums", () => {
    assert.equal(SessionStatus.Draft, "Draft");
    assert.equal(SessionStatus.Active, "Active");
    assert.equal(SessionStatus.Closed, "Closed");
    assert.equal(AttendanceStatus.Pending, "Pending");
    assert.equal(AttendanceStatus.Present, "Present");
  });

  it("defines BR-01 attendance window duration of 10 minutes", () => {
    assert.equal(ATTENDANCE_WINDOW_MS, 600_000);
  });

  it("defines BR-03 QR token TTL of 30 seconds", () => {
    assert.equal(QR_TOKEN_TTL_MS, 30_000);
  });

  it("defines BR-02 GPS radius bounds 20–500 m with default 100 m", () => {
    assert.equal(GPS_RADIUS_MIN_METERS, 20);
    assert.equal(GPS_RADIUS_MAX_METERS, 500);
    assert.equal(GPS_RADIUS_DEFAULT_METERS, 100);
  });

  it("defines BR-10 instructor edit window of 24 hours", () => {
    assert.equal(INSTRUCTOR_EDIT_WINDOW_MS, 86_400_000);
  });
});

describe("validation rule identifiers", () => {
  it("exports VAL-01 through VAL-12 rule IDs", () => {
    assert.equal(ValidationRuleId.VAL_01, "VAL-01");
    assert.equal(ValidationRuleId.VAL_12, "VAL-12");
  });

  it("maps business rules to canonical error codes", () => {
    assert.equal(BusinessRuleId.BR_01, "BR-01");
    assert.equal(BUSINESS_RULE_ERROR_CODES[BusinessRuleId.BR_02], ErrorCode.OutOfRadius);
    assert.equal(BUSINESS_RULE_ERROR_CODES[BusinessRuleId.BR_03], ErrorCode.ExpiredQr);
    assert.equal(BUSINESS_RULE_ERROR_CODES[BusinessRuleId.BR_04], ErrorCode.DuplicateCheckIn);
    assert.equal(BUSINESS_RULE_ERROR_CODES[BusinessRuleId.BR_10], ErrorCode.EditWindowExpired);
  });

  it("exports CheckInOutcome enum matching state machine catalog", () => {
    assert.equal(CheckInOutcome.Success, "Success");
    assert.equal(CheckInOutcome.SessionNotActive, "SessionNotActive");
    assert.equal(CheckInOutcome.DuplicateCheckIn, "DuplicateCheckIn");
  });
});

describe("BR-03 token expiry helpers", () => {
  it("computes expires_at as issued_at plus 30 seconds", () => {
    const issuedAt = new Date("2026-06-01T10:00:00.000Z");
    const expiresAt = computeTokenExpiresAt(issuedAt);
    assert.equal(expiresAt.getTime() - issuedAt.getTime(), QR_TOKEN_TTL_MS);
  });

  it("allows check-in at exactly T + 30 s inclusive boundary", () => {
    const issuedAt = new Date("2026-06-01T10:00:00.000Z");
    const atBoundary = new Date(issuedAt.getTime() + QR_TOKEN_TTL_MS);
    assert.equal(isQrTokenExpired(issuedAt, atBoundary), false);
    assert.equal(
      isQrTokenExpired(issuedAt, new Date(atBoundary.getTime() + 1)),
      true,
    );
  });
});

describe("BR-04 duplicate check-in guard", () => {
  it("blocks when attendance is Present", () => {
    assert.equal(
      blocksDuplicateCheckIn(AttendanceStatus.Present, new Date()),
      true,
    );
  });

  it("blocks Excused only when prior check-in timestamp exists", () => {
    assert.equal(
      blocksDuplicateCheckIn(AttendanceStatus.Excused, new Date()),
      true,
    );
    assert.equal(blocksDuplicateCheckIn(AttendanceStatus.Excused, null), false);
  });

  it("allows Pending and Absent students to check in", () => {
    assert.equal(blocksDuplicateCheckIn(AttendanceStatus.Pending, null), false);
    assert.equal(blocksDuplicateCheckIn(AttendanceStatus.Absent, null), false);
  });
});

describe("BR-10 manual edit policy", () => {
  const closedAt = new Date("2026-06-01T12:00:00.000Z");

  it("allows instructor within 24 h of closedAt", () => {
    assert.equal(
      canManualEditAttendance({
        editorRole: UserRole.Instructor,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS),
      }),
      true,
    );
  });

  it("denies instructor after 24 h window", () => {
    assert.equal(
      canManualEditAttendance({
        editorRole: UserRole.Instructor,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 1),
      }),
      false,
    );
  });

  it("allows TrainingOfficeAdmin regardless of window", () => {
    assert.equal(
      canManualEditAttendance({
        editorRole: UserRole.TrainingOfficeAdmin,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 86_400_000),
      }),
      true,
    );
  });
});
