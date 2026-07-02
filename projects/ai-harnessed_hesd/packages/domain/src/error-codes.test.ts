import { describe, expect, it } from "vitest";
import { ERROR_CODE_GROUPS, ErrorCode, isErrorCode } from "./error-codes.js";

describe("ErrorCode catalog", () => {
  it("exposes canonical validation error codes per 08-validation-rules §6.2", () => {
    expect(ErrorCode.SessionNotOpen).toBe("SessionNotOpen");
    expect(ErrorCode.ExpiredQr).toBe("ExpiredQr");
    expect(ErrorCode.DuplicateCheckIn).toBe("DuplicateCheckIn");
    expect(ErrorCode.OutOfScope).toBe("OutOfScope");
  });

  it("groups codes by domain concern without duplicates", () => {
    const all = Object.values(ERROR_CODE_GROUPS).flat();
    const unique = new Set(all);
    expect(unique.size).toBe(all.length);
    expect(unique.has(ErrorCode.Unauthenticated)).toBe(true);
    expect(unique.has(ErrorCode.InvalidPayload)).toBe(true);
  });

  it("isErrorCode narrows unknown strings", () => {
    expect(isErrorCode("NotEnrolled")).toBe(true);
    expect(isErrorCode("NotARealCode")).toBe(false);
  });
});
