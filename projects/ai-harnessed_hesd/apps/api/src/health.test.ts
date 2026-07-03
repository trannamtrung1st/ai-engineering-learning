import { describe, expect, it } from "vitest";
import type { HealthPayload } from "@attendly/domain";

function buildHealthPayload(dbConnected: boolean): HealthPayload {
  return {
    status: dbConnected ? "ok" : "degraded",
    db: dbConnected ? "connected" : "disconnected",
  };
}

describe("health payload — NFR-16", () => {
  it("marks platform ok when database probe succeeds", () => {
    expect(buildHealthPayload(true)).toEqual({ status: "ok", db: "connected" });
  });

  it("marks platform degraded when database probe fails", () => {
    expect(buildHealthPayload(false)).toEqual({
      status: "degraded",
      db: "disconnected",
    });
  });
});
