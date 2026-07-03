/**
 * Traceability: FR-37 BR-19 PRM-03
 */
import { describe, expect, it } from "vitest";
import type { ActorContext } from "../identity/types.js";
import { resolveReportExportScope } from "./scope.js";

const studentActor: ActorContext = {
  userId: "60000000-0000-4000-8000-000000000002",
  email: "student1@attendly.local",
  displayName: "Student",
  roles: ["Student"],
  assignments: [{ role: "Student", scopeType: "Self", scopeId: "60000000-0000-4000-8000-000000000002" }],
};

describe("reporting scope — FR-37 student self-scope", () => {
  it("TC-FR-37-001 TC-FR-37-009 PRM-03: denies studentUserId override for another student", async () => {
    const repository = {
      getStudentEnrolledSectionIds: async () => ["sec-a"],
      resolveScopeBindings: async () => ({}),
      getLecturerClassSectionIds: async () => [],
    };

    const result = await resolveReportExportScope(
      studentActor,
      repository as never,
      { studentUserId: "other-student" },
      "ReportView",
    );

    expect(result).toEqual({ allowed: false, code: "Forbidden" });
  });

  it("TC-FR-37-002 PRM-03: allows student report read with mandatory self studentUserId scope", async () => {
    const repository = {
      getStudentEnrolledSectionIds: async () => ["sec-a", "sec-b"],
      resolveScopeBindings: async () => ({}),
      getLecturerClassSectionIds: async () => [],
    };

    const result = await resolveReportExportScope(
      studentActor,
      repository as never,
      { termId: "term-1" },
      "ReportView",
    );

    expect(result).toEqual({
      allowed: true,
      scope: {
        classSectionIds: ["sec-a", "sec-b"],
        studentUserId: studentActor.userId,
      },
    });
  });

  it("still denies student export execution", async () => {
    const repository = {
      getStudentEnrolledSectionIds: async () => ["sec-a"],
      resolveScopeBindings: async () => ({}),
      getLecturerClassSectionIds: async () => [],
    };

    const result = await resolveReportExportScope(
      studentActor,
      repository as never,
      { termId: "term-1" },
      "ExportJob",
    );

    expect(result).toEqual({ allowed: false, code: "Forbidden" });
  });
});
