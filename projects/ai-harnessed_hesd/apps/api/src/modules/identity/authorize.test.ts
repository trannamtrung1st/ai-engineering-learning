import { describe, expect, it } from "vitest";
import { authorize } from "./authorize.js";
import type { ActorContext } from "./types.js";

const lecturerActor: ActorContext = {
  userId: "lecturer-1",
  email: "lecturer@test.local",
  displayName: "Lecturer",
  roles: ["Lecturer"],
  assignments: [
    { role: "Lecturer", scopeType: "ClassSection", scopeId: "section-a" },
  ],
};

const studentActor: ActorContext = {
  userId: "student-1",
  email: "student@test.local",
  displayName: "Student",
  roles: ["Student"],
  assignments: [{ role: "Student", scopeType: "Self", scopeId: "student-1" }],
};

const academicAdminActor: ActorContext = {
  userId: "admin-1",
  email: "admin@test.local",
  displayName: "Admin",
  roles: ["AcademicAdmin"],
  assignments: [{ role: "AcademicAdmin", scopeType: "Institution", scopeId: null }],
};

const auditorActor: ActorContext = {
  userId: "auditor-1",
  email: "auditor@test.local",
  displayName: "Auditor",
  roles: ["SystemAuditor"],
  assignments: [{ role: "SystemAuditor", scopeType: "Institution", scopeId: null }],
};

describe("authorize — FR-31 FR-32 BR-19 NFR-09", () => {
  it("denies Student report read with Forbidden (BR-19)", () => {
    const decision = authorize(studentActor, "ReportView", "read", {});
    expect(decision).toEqual({
      allowed: false,
      code: "Forbidden",
      reason: expect.stringContaining("ReportView"),
    });
  });

  it("allows Lecturer report read within assigned class section (PRM-01)", () => {
    const decision = authorize(
      lecturerActor,
      "ReportView",
      "read",
      { classSectionId: "section-a" },
      { lecturerClassSectionIds: ["section-a"] },
    );
    expect(decision).toEqual({ allowed: true });
  });

  it("denies Lecturer report read for unassigned section with OutOfScope (BR-19)", () => {
    const decision = authorize(
      lecturerActor,
      "ReportView",
      "read",
      { classSectionId: "section-b" },
      { lecturerClassSectionIds: ["section-a"] },
    );
    expect(decision.allowed).toBe(false);
    if (!decision.allowed) {
      expect(decision.code).toBe("OutOfScope");
    }
  });

  it("denies SystemAuditor export execute with Forbidden (FR-32)", () => {
    const decision = authorize(auditorActor, "ExportJob", "execute", {});
    expect(decision.allowed).toBe(false);
    if (!decision.allowed) {
      expect(decision.code).toBe("Forbidden");
    }
  });

  it("allows AcademicAdmin institution-scoped report read", () => {
    const decision = authorize(academicAdminActor, "ReportView", "read", {});
    expect(decision).toEqual({ allowed: true });
  });

  it("denies Student audit log read (NFR-09)", () => {
    const decision = authorize(studentActor, "AuditLog", "read", {});
    expect(decision.allowed).toBe(false);
    if (!decision.allowed) {
      expect(decision.code).toBe("Forbidden");
    }
  });

  it("allows Student check-in submit for self scope (FR-15)", () => {
    const decision = authorize(
      studentActor,
      "CheckInSubmit",
      "execute",
      { studentUserId: "student-1" },
    );
    expect(decision).toEqual({ allowed: true });
  });

  it("denies Lecturer check-in submit with Forbidden (FR-15)", () => {
    const decision = authorize(lecturerActor, "CheckInSubmit", "execute", {});
    expect(decision.allowed).toBe(false);
    if (!decision.allowed) {
      expect(decision.code).toBe("Forbidden");
    }
  });
});
