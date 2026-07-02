import { describe, expect, it } from "vitest";
import { resolveStudentEmail } from "./student-login";

describe("resolveStudentEmail (FR-15 AC-06)", () => {
  it("maps seed student codes to institution emails", () => {
    expect(resolveStudentEmail("SV001")).toBe("student1@attendly.local");
    expect(resolveStudentEmail("sv002")).toBe("student2@attendly.local");
  });

  it("passes through email-shaped login identifiers", () => {
    expect(resolveStudentEmail("student1@attendly.local")).toBe("student1@attendly.local");
  });
});
