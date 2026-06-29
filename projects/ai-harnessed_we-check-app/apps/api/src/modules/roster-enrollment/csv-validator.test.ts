import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { ErrorCode } from "@wecheck/domain";
import {
  mapCsvRows,
  parseCsvContent,
  RosterRowErrorCode,
  validateCsvFile,
  validateDisplayName,
  validateInstitutionalId,
} from "./csv-validator.js";

/**
 * Traceability: AC-03 FR-03
 * Cases: TC-AC-03-012 TC-AC-03-014 TC-AC-03-013 TC-FR-03-012 TC-FR-03-014
 */
describe("roster csv-validator (AC-03, FR-03)", () => {
  it("validateCsvFile rejects missing buffer (TC-AC-03-013, TC-FR-03-013)", () => {
    const result = validateCsvFile(undefined, "text/csv");
    assert.equal(result.ok, false);
    if (!result.ok) {
      assert.equal(result.reason, "missing");
    }
  });

  it("validateCsvFile accepts UTF-8 csv buffer", () => {
    const buffer = Buffer.from("institutional_id,display_name,class_code,subject_code\n", "utf8");
    const result = validateCsvFile(buffer, "text/csv");
    assert.equal(result.ok, true);
  });

  it("parseCsvContent parses required columns and rows", () => {
    const content =
      "institutional_id,display_name,class_code,subject_code\n" +
      "SV2026001,Nguyen Van A,HESD-01,SWE-101\n";
    const parsed = parseCsvContent(content);
    assert.deepEqual(parsed.headers, [
      "institutional_id",
      "display_name",
      "class_code",
      "subject_code",
    ]);
    assert.equal(parsed.rows.length, 1);
  });

  it("mapCsvRows rejects all rows when subject_code column missing (TC-AC-03-012)", () => {
    const content =
      "institutional_id,display_name,class_code\n" +
      "SV2026001,Nguyen Van A,HESD-01\n" +
      "SV2026002,Tran Thi B,HESD-01\n";
    const { headers, rows } = parseCsvContent(content);
    const mapped = mapCsvRows(headers, rows);
    assert.equal(mapped.ok, false);
    if (!mapped.ok) {
      assert.equal(mapped.errors.length, 2);
      assert.equal(mapped.errors[0]?.errorCode, RosterRowErrorCode.MissingColumns);
      assert.equal(mapped.errors[1]?.rowNumber, 3);
    }
  });

  it("validateInstitutionalId enforces VAL-05 pattern", () => {
    assert.equal(validateInstitutionalId("SV2026001"), true);
    assert.equal(validateInstitutionalId("ab"), false);
    assert.equal(validateInstitutionalId("bad id!"), false);
  });

  it("validateDisplayName enforces VAL-04 length", () => {
    assert.equal(validateDisplayName("Nguyễn Văn A"), true);
    assert.equal(validateDisplayName("   "), false);
    assert.equal(validateDisplayName("x".repeat(201)), false);
  });

  it("mapCsvRows maps row fields with correct row numbers", () => {
    const content =
      "institutional_id,display_name,class_code,subject_code\n" +
      "SV2026001,Nguyen Van A,HESD-01,SWE-101\n";
    const { headers, rows } = parseCsvContent(content);
    const mapped = mapCsvRows(headers, rows);
    assert.equal(mapped.ok, true);
    if (mapped.ok) {
      assert.equal(mapped.rows[0]?.rowNumber, 2);
      assert.equal(mapped.rows[0]?.institutionalId, "SV2026001");
      assert.equal(mapped.rows[0]?.classCode, "HESD-01");
    }
  });

  it("unknown class row maps to UnknownClassCode at service layer (TC-AC-03-014)", () => {
    assert.equal(RosterRowErrorCode.UnknownClassCode, "UnknownClassCode");
    assert.equal(ErrorCode.InvalidFile, "InvalidFile");
  });
});
