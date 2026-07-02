import { describe, expect, it } from "vitest";
import { accessTokenExpirySeconds, signAccessToken, verifyAccessToken } from "./jwt.js";

describe("jwt access tokens — FR-15 FR-36", () => {
  it("round-trips claims for authenticated API calls", async () => {
    process.env.JWT_SECRET = "unit-test-secret";
    const token = await signAccessToken({
      sub: "60000000-0000-4000-8000-000000000002",
      email: "student1@attendly.local",
      roles: ["Student"],
    });

    const claims = await verifyAccessToken(token);
    expect(claims.sub).toBe("60000000-0000-4000-8000-000000000002");
    expect(claims.email).toBe("student1@attendly.local");
    expect(claims.roles).toEqual(["Student"]);
    expect(accessTokenExpirySeconds()).toBe(3600);
  });

  it("rejects malformed bearer tokens with error", async () => {
    process.env.JWT_SECRET = "unit-test-secret";
    await expect(verifyAccessToken("not-a-jwt")).rejects.toThrow();
  });
});
