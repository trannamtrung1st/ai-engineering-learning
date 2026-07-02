import { describe, expect, it } from "vitest";
import { capabilityForRole, rolesWithCapability } from "./permissions.js";

describe("permissions matrix — NFR-09 RBAC-01", () => {
  it("denies Student ExportJob.execute by default", () => {
    expect(capabilityForRole("Student", "ExportJob", "execute")).toBe("deny");
  });

  it("scopes Lecturer ExportJob.execute to assigned sections", () => {
    expect(capabilityForRole("Lecturer", "ExportJob", "execute")).toBe("scoped");
  });

  it("allows AcademicAdmin ReportView.read institution-wide", () => {
    expect(capabilityForRole("AcademicAdmin", "ReportView", "read")).toBe("allow");
  });

  it("lists roles that may read audit logs", () => {
    const roles = rolesWithCapability("AuditLog", "read");
    expect(roles).toContain("AcademicAdmin");
    expect(roles).toContain("SystemAuditor");
    expect(roles).not.toContain("Student");
  });
});
