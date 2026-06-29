import { describe, expect, it } from "vitest";
import { mapCheckInOutcome } from "@/lib/check-in-api";

/** NFR-06 — stale QR token maps to ExpiredQr outcome */
describe("check-in-api (NFR-06)", () => {
  it("maps ExpiredQr errorCode to ExpiredQr outcome", () => {
    expect(mapCheckInOutcome("ExpiredQr", "ExpiredQr")).toBe("ExpiredQr");
  });

  it("maps TokenNotFound to ExpiredQr and TokenAlreadyUsed distinctly (BR-11)", () => {
    expect(mapCheckInOutcome("TokenNotFound", "TokenNotFound")).toBe("ExpiredQr");
    expect(mapCheckInOutcome("TokenAlreadyUsed", "TokenAlreadyUsed")).toBe("TokenAlreadyUsed");
  });

  it("maps Unauthenticated to NetworkError for auth redirect handling", () => {
    expect(mapCheckInOutcome("", "Unauthenticated")).toBe("NetworkError");
  });

  it("maps Success to Present", () => {
    expect(mapCheckInOutcome("Success")).toBe("Present");
  });
});
