import { describe, expect, it } from "vitest";
import { createMeta, successEnvelope } from "./api-envelope.js";
import { ErrorCode } from "./error-codes.js";

/**
 * Monorepo foundation checks — FR-33 shared contract scaffold for platform operations
 * and NFR-16 operational telemetry types consumed by API workspaces.
 */
describe("monorepo foundation — FR-33 NFR-16", () => {
  it("FR-33: shared domain package exports stable error codes for API contract", () => {
    expect(ErrorCode.Forbidden).toBe("Forbidden");
    expect(ErrorCode.OutOfScope).toBe("OutOfScope");
  });

  it("NFR-16: API envelope meta supports requestId and timestamp for operational logs", () => {
    const meta = createMeta("req-ops-1");
    expect(meta.requestId).toBe("req-ops-1");
    expect(meta.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("NFR-16: success envelope matches documented { data, meta, error } shape", () => {
    const envelope = successEnvelope({ status: "ok" }, "health-req");
    expect(envelope.error).toBeNull();
    expect(envelope.data).toEqual({ status: "ok" });
    expect(envelope.meta.requestId).toBe("health-req");
  });
});
