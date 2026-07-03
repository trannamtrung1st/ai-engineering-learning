/**
 * Performance smoke fixture constants — AC-20 AC-21 AC-22 NFR-01 NFR-03
 */
import { describe, expect, it } from "vitest";
import {
  PERF_IT_ADMIN_SEED,
  PERF_SMOKE_EMAILS,
  PERF_SMOKE_SEED,
  PERF_STUDENTS_PER_SECTION,
  allPerfStudentIds,
  perfStudentEmail,
  perfStudentId,
} from "./performance-smoke-fixtures.js";

describe("performance smoke fixtures — AC-20 AC-21 AC-22", () => {
  it("seeds 20 students per section for class-start burst profile", () => {
    expect(PERF_STUDENTS_PER_SECTION).toBeGreaterThanOrEqual(20);
    expect(allPerfStudentIds()).toHaveLength(PERF_STUDENTS_PER_SECTION * 2);
  });

  it("uses deterministic student IDs and emails per section", () => {
    expect(perfStudentId(0, 0)).toBe("61000000-0000-4000-8000-000000000001");
    expect(perfStudentEmail(0, 0)).toBe("perf-student-01@attendly.local");
    expect(perfStudentId(1, 0)).toBe("61000000-0000-4000-8000-000000000021");
    expect(perfStudentEmail(1, 0)).toBe("perf-student-21@attendly.local");
  });

  it("defines preview ITAdmin actor for NFR-16 PG-15 smoke", () => {
    expect(PERF_SMOKE_EMAILS.itAdmin).toBe("e2e-itadmin@attendly.local");
    expect(PERF_IT_ADMIN_SEED.userId).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("keeps performance hierarchy isolated from critical-path seed IDs", () => {
    expect(PERF_SMOKE_SEED.sectionA).not.toBe("50000000-0000-4000-8000-000000000088");
    expect(PERF_SMOKE_SEED.course).not.toBe("30000000-0000-4000-8000-000000000088");
  });
});
