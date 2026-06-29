import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  INSTRUCTOR_EDIT_WINDOW_MS,
  SessionStatus,
  UserRole,
} from "@wecheck/domain";
import {
  assertManualEditAllowed,
  canManualEditAttendance,
  isWithinInstructorEditWindow,
} from "./edit-window-policy.js";

/** Traceability: AC-11 AC-14 FR-11 FR-14 BR-10 NFR-15 — TC-AC-11-014 TC-FR-11-014 TC-BR-10-014 */
describe("edit-window-policy (BR-10)", () => {
  const closedAt = new Date("2026-06-01T12:00:00.000Z");

  it("allows instructor within 24 h of closedAt inclusive", () => {
    assert.equal(
      assertManualEditAllowed({
        editorRole: UserRole.Instructor,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS),
      }),
      true,
    );
    assert.equal(
      isWithinInstructorEditWindow(
        closedAt,
        new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS),
      ),
      true,
    );
  });

  it("denies instructor one millisecond after 24 h window", () => {
    assert.equal(
      assertManualEditAllowed({
        editorRole: UserRole.Instructor,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 1),
      }),
      false,
    );
    assert.equal(
      isWithinInstructorEditWindow(
        closedAt,
        new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 1),
      ),
      false,
    );
  });

  it("allows TrainingOfficeAdmin regardless of elapsed time", () => {
    assert.equal(
      assertManualEditAllowed({
        editorRole: UserRole.TrainingOfficeAdmin,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: new Date(closedAt.getTime() + INSTRUCTOR_EDIT_WINDOW_MS + 86_400_000),
      }),
      true,
    );
  });

  it("allows instructor edits while session is Active", () => {
    assert.equal(
      canManualEditAttendance({
        editorRole: UserRole.Instructor,
        sessionStatus: SessionStatus.Active,
        closedAt: null,
        now: new Date(),
      }),
      true,
    );
  });

  it("denies edits when session is Draft or Cancelled", () => {
    for (const status of [SessionStatus.Draft, SessionStatus.Cancelled]) {
      assert.equal(
        assertManualEditAllowed({
          editorRole: UserRole.Instructor,
          sessionStatus: status,
          closedAt: null,
          now: new Date(),
        }),
        false,
      );
    }
  });

  it("denies student role from manual edit policy", () => {
    assert.equal(
      assertManualEditAllowed({
        editorRole: UserRole.Student,
        sessionStatus: SessionStatus.Closed,
        closedAt,
        now: closedAt,
      }),
      false,
    );
  });
});
