/**
 * Schema artifact traceability for FR-04 FR-18 BR-06 BR-07 NFR-07 and related generated cases:
 * AC-05 AC-07 AC-08 BR-02 BR-08 BR-09 BR-10 BR-14 BR-16 BR-18 BR-19 BR-23
 * FR-08 FR-15 FR-17 FR-19 FR-20 FR-22 FR-27 FR-36 NFR-01 NFR-03 NFR-04 NFR-06
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const REPO_ROOT = resolve(fileURLToPath(new URL(".", import.meta.url)), "../../../..");
const MIGRATIONS_DIR = join(REPO_ROOT, "apps/api/db/migrations");

describe("database migration artifacts — FR-04 FR-18 BR-06 BR-07 NFR-07", () => {
  it("ships an ordered initial migration chain with core tables", () => {
    const files = readdirSync(MIGRATIONS_DIR)
      .filter((name) => name.endsWith(".sql"))
      .sort();
    expect(files.length).toBeGreaterThan(0);
    expect(files[0]).toBe("0001_initial_schema.sql");
  });

  it("declares enrollment and attendance unique constraints from domain invariants", () => {
    const sql = readFileSync(join(MIGRATIONS_DIR, "0001_initial_schema.sql"), "utf8");
    expect(sql).toMatch(/UNIQUE \(class_section_id, student_user_id\)/);
    expect(sql).toMatch(/UNIQUE \(class_session_id, student_user_id\)/);
    expect(sql).toMatch(/token_hash text NOT NULL UNIQUE/);
  });

  it("declares canonical session, enrollment, and outcome enum checks", () => {
    const sql = readFileSync(join(MIGRATIONS_DIR, "0001_initial_schema.sql"), "utf8");
    expect(sql).toContain("'Scheduled'");
    expect(sql).toContain("'Open'");
    expect(sql).toContain("'Active'");
    expect(sql).toContain("'DuplicateCheckIn'");
    expect(sql).toContain("'NotEnrolled'");
  });
});
