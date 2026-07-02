import { describe, expect, it } from "vitest";
import { resolveCheckInSuccessCopy } from "./success-copy";

describe("resolveCheckInSuccessCopy (FR-23 AC-11)", () => {
  it("returns success-present Vietnamese copy for Present status", () => {
    const copy = resolveCheckInSuccessCopy("Present");
    expect(copy.state).toBe("success-present");
    expect(copy.title).toContain("Có mặt");
  });

  it("returns success-late warning copy for Late status", () => {
    const copy = resolveCheckInSuccessCopy("Late");
    expect(copy.state).toBe("success-late");
    expect(copy.title).toContain("Đi trễ");
  });
});
