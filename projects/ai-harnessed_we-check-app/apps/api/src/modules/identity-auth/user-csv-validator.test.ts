import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ErrorCode, UserRole } from "@wecheck/domain";
import {
  mapUserCsvRows,
  parseUserActive,
  parseUserCsvContent,
  USER_REQUIRED_CSV_COLUMNS,
  validateUserCsvFile,
  validateUserDisplayName,
  validateUserEmail,
  validateUserImportRow,
  validateUserInstitutionalId,
} from "./user-import-csv.js";

/**
 * Traceability: AC-01 FR-01 NFR-11
 * Cases: TC-FR-01-023 TC-AC-01-006 TC-FR-01-020
 */
describe("user CSV validator (AC-01, FR-01, VAL-05)", () => {
  it("validateUserInstitutionalId accepts underscore and period (VAL-05, AC-01f)", () => {
    assert.equal(validateUserInstitutionalId("SV_2026.001"), true);
    assert.equal(validateUserInstitutionalId("SV_2026.002"), true);
    assert.equal(validateUserInstitutionalId("SV2026001"), true);
    assert.equal(validateUserInstitutionalId("ab"), false);
    assert.equal(validateUserInstitutionalId("has space"), false);
  });

  it("validateUserEmail normalizes to lowercase", () => {
    assert.equal(validateUserEmail("  Student@Example.Edu.VN  "), true);
  });

  it("validateUserDisplayName enforces 1-200 chars", () => {
    assert.equal(validateUserDisplayName(""), false);
    assert.equal(validateUserDisplayName("Nguyễn Văn A"), true);
    assert.equal(validateUserDisplayName("a".repeat(201)), false);
  });

  it("parseUserActive accepts true/false variants", () => {
    assert.equal(parseUserActive("true"), true);
    assert.equal(parseUserActive("1"), true);
    assert.equal(parseUserActive("false"), false);
    assert.equal(parseUserActive("0"), false);
    assert.equal(parseUserActive("yes"), null);
  });

  it("parseUserCsvContent strips BOM and normalizes headers", () => {
    const { headers, rows } = parseUserCsvContent(
      "\uFEFFinstitutional_id,display_name,email,role,active\nSV1,Name,a@b.c,Student,true",
    );
    assert.deepEqual(headers, [...USER_REQUIRED_CSV_COLUMNS]);
    assert.equal(rows.length, 1);
  });

  it("mapUserCsvRows rejects missing required columns", () => {
    const { headers, rows } = parseUserCsvContent("institutional_id,email\nSV1,a@b.c");
    const mapped = mapUserCsvRows(headers, rows);
    assert.equal(mapped.ok, false);
    if (!mapped.ok) {
      assert.equal(mapped.errors[0]?.errorCode, "MissingColumns");
    }
  });

  it("validateUserImportRow rejects invalid institutional_id", () => {
    const { headers, rows } = parseUserCsvContent(
      "institutional_id,display_name,email,role,active\nab,Name,a@b.c,Student,true",
    );
    const mapped = mapUserCsvRows(headers, rows);
    assert.equal(mapped.ok, true);
    if (mapped.ok) {
      const error = validateUserImportRow(mapped.rows[0]!);
      assert.equal(error?.errorCode, ErrorCode.InvalidInstitutionalId);
      assert.equal(error?.field, "institutional_id");
    }
  });

  it("validateUserImportRow accepts SV_2026.002 row (TC-FR-01-023, AC-01f)", () => {
    const { headers, rows } = parseUserCsvContent(
      "institutional_id,display_name,email,role,active\nSV_2026.002,Period Student,period002@example.edu.vn,Student,true",
    );
    const mapped = mapUserCsvRows(headers, rows);
    assert.equal(mapped.ok, true);
    if (mapped.ok) {
      assert.equal(validateUserImportRow(mapped.rows[0]!), null);
      assert.equal(mapped.rows[0]?.role, UserRole.Student);
    }
  });

  it("validateUserCsvFile rejects missing and oversized files", () => {
    assert.equal(validateUserCsvFile(undefined, undefined).ok, false);
    assert.equal(validateUserCsvFile(Buffer.alloc(0), undefined).ok, false);
    assert.equal(validateUserCsvFile(Buffer.from("a"), "text/csv").ok, true);
    assert.equal(
      validateUserCsvFile(Buffer.alloc(5 * 1024 * 1024 + 1), "text/csv").ok,
      false,
    );
  });
});
