import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildLoginRedirectUrl,
  isOrganizerRole,
  isParticipantRole,
  isSafeReturnUrl,
  resolvePostAuthRedirect,
} from "./auth-redirect.js";

describe("auth redirect helpers (AC-15, FR-34)", () => {
  it("buildLoginRedirectUrl preserves pathname and query", () => {
    assert.equal(
      buildLoginRedirectUrl("/registrations", "page=2"),
      "/login?returnUrl=%2Fregistrations%3Fpage%3D2",
    );
  });

  it("resolvePostAuthRedirect honors safe returnUrl", () => {
    assert.equal(
      resolvePostAuthRedirect("/registrations", "Participant"),
      "/registrations",
    );
  });

  it("resolvePostAuthRedirect rejects auth pages and external URLs", () => {
    assert.equal(resolvePostAuthRedirect("/login", "Participant"), "/events");
    assert.equal(resolvePostAuthRedirect("//evil.test", "Participant"), "/events");
  });

  it("resolvePostAuthRedirect lands organizers on console by default", () => {
    assert.equal(
      resolvePostAuthRedirect(null, "OrganizerAdmin"),
      "/organizer/events",
    );
  });

  it("isSafeReturnUrl blocks login and signup loops", () => {
    assert.equal(isSafeReturnUrl("/events"), true);
    assert.equal(isSafeReturnUrl("/login"), false);
    assert.equal(isSafeReturnUrl("/signup"), false);
  });

  it("role guards distinguish participant and organizer sessions", () => {
    assert.equal(isParticipantRole("Participant"), true);
    assert.equal(isParticipantRole("OrganizerAdmin"), false);
    assert.equal(isOrganizerRole("OrganizerStaff"), true);
    assert.equal(isOrganizerRole("Participant"), false);
  });
});
