import { describe, expect, it } from "vitest";
import { ErrorCode } from "@attendly/domain";
import {
  attemptOutcomeLabel,
  formatOutOfRadiusReviewMeta,
  isRejectedAttemptOutcome,
} from "./attempt-outcomes";

/** Traceability: FR-19 AC-18 AC-25 AC-10 NFR-17 */
describe("attempt-outcomes — FR-19 AC-18 AC-25 AC-10 NFR-17", () => {
  it("maps OutOfRadius to Vietnamese label", () => {
    expect(attemptOutcomeLabel(ErrorCode.OutOfRadius)).toBe("Ngoài phạm vi");
    expect(isRejectedAttemptOutcome(ErrorCode.OutOfRadius)).toBe(true);
  });

  it("TC-AC-10-010: formats out-of-radius review metadata", () => {
    expect(formatOutOfRadiusReviewMeta(162.8, 100)).toBe("163m · giới hạn 100m");
    expect(formatOutOfRadiusReviewMeta(null, 100)).toBeNull();
  });

  it("ignores Success outcomes in roster rejection column", () => {
    expect(isRejectedAttemptOutcome("Success")).toBe(false);
    expect(attemptOutcomeLabel("Success")).toBeNull();
  });
});
