import { describe, expect, it } from "vitest";
import { ErrorCode } from "@attendly/domain";
import { attemptOutcomeLabel, isRejectedAttemptOutcome } from "./attempt-outcomes";

/** Traceability: FR-19 AC-18 AC-25 NFR-17 */
describe("attempt-outcomes — FR-19 AC-18 AC-25 NFR-17", () => {
  it("maps OutOfRadius to Vietnamese label", () => {
    expect(attemptOutcomeLabel(ErrorCode.OutOfRadius)).toBe("Ngoài phạm vi");
    expect(isRejectedAttemptOutcome(ErrorCode.OutOfRadius)).toBe(true);
  });

  it("ignores Success outcomes in roster rejection column", () => {
    expect(isRejectedAttemptOutcome("Success")).toBe(false);
    expect(attemptOutcomeLabel("Success")).toBeNull();
  });
});
