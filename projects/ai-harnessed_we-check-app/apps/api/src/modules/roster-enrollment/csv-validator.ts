import { ErrorCode } from "@wecheck/domain";
import type { ImportErrorDetail, ParsedCsvRow } from "./types.js";

export const RosterRowErrorCode = {
  MissingColumns: "MissingColumns",
  InvalidInstitutionalId: "InvalidInstitutionalId",
  InvalidDisplayName: "InvalidDisplayName",
  UnknownClassCode: "UnknownClassCode",
  UnknownSubjectCode: "UnknownSubjectCode",
  DuplicateEnrollment: "DuplicateEnrollment",
} as const;

export type RosterRowErrorCode =
  (typeof RosterRowErrorCode)[keyof typeof RosterRowErrorCode];

export const ROSTER_ROW_ERROR_MESSAGES: Readonly<Record<RosterRowErrorCode, string>> = {
  [RosterRowErrorCode.MissingColumns]: "Thiếu cột bắt buộc trong file CSV",
  [RosterRowErrorCode.InvalidInstitutionalId]: "Mã sinh viên không hợp lệ",
  [RosterRowErrorCode.InvalidDisplayName]: "Tên hiển thị không hợp lệ",
  [RosterRowErrorCode.UnknownClassCode]: "Mã lớp không tồn tại",
  [RosterRowErrorCode.UnknownSubjectCode]: "Mã môn học không tồn tại",
  [RosterRowErrorCode.DuplicateEnrollment]: "Sinh viên đã được ghi danh cho lớp-môn này",
};

export const REQUIRED_CSV_COLUMNS = [
  "institutional_id",
  "display_name",
  "class_code",
  "subject_code",
] as const;

const INSTITUTIONAL_ID_RE = /^[A-Za-z0-9-]{3,32}$/;
const MAX_FILE_BYTES = 5 * 1024 * 1024;

export function validateCsvFile(
  buffer: Buffer | undefined,
  mimeType: string | undefined,
): { ok: true; buffer: Buffer } | { ok: false; reason: "missing" | "invalid" } {
  if (!buffer || buffer.length === 0) {
    return { ok: false, reason: "missing" };
  }
  if (buffer.length > MAX_FILE_BYTES) {
    return { ok: false, reason: "invalid" };
  }
  if (
    mimeType &&
    mimeType !== "text/csv" &&
    mimeType !== "application/csv" &&
    mimeType !== "text/plain" &&
    !mimeType.includes("csv")
  ) {
    return { ok: false, reason: "invalid" };
  }
  return { ok: true, buffer };
}

function parseCsvLine(line: string): string[] {
  const fields: string[] = [];
  let current = "";
  let inQuotes = false;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];
    if (char === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"';
        i += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === "," && !inQuotes) {
      fields.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  fields.push(current.trim());
  return fields;
}

export function parseCsvContent(content: string): {
  headers: string[];
  rows: string[][];
} {
  const normalized = content.replace(/^\uFEFF/, "").trim();
  if (!normalized) {
    return { headers: [], rows: [] };
  }

  const lines = normalized.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length === 0) {
    return { headers: [], rows: [] };
  }

  const headers = parseCsvLine(lines[0]!).map((h) => h.toLowerCase());
  const rows = lines.slice(1).map(parseCsvLine);
  return { headers, rows };
}

export function validateInstitutionalId(value: string): boolean {
  return INSTITUTIONAL_ID_RE.test(value.trim());
}

export function validateDisplayName(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length >= 1 && trimmed.length <= 200;
}

export function mapCsvRows(
  headers: string[],
  rows: string[][],
): { ok: true; rows: ParsedCsvRow[] } | { ok: false; errors: ImportErrorDetail[] } {
  const missingColumns = REQUIRED_CSV_COLUMNS.filter(
    (col) => !headers.includes(col),
  );
  if (missingColumns.length > 0) {
    const errors: ImportErrorDetail[] = rows.map((_, index) => ({
      rowNumber: index + 2,
      errorCode: RosterRowErrorCode.MissingColumns,
      message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.MissingColumns],
    }));
    return { ok: false, errors };
  }

  const columnIndex = Object.fromEntries(
    REQUIRED_CSV_COLUMNS.map((col) => [col, headers.indexOf(col)]),
  ) as Record<(typeof REQUIRED_CSV_COLUMNS)[number], number>;

  const parsed: ParsedCsvRow[] = rows.map((cells, index) => ({
    rowNumber: index + 2,
    institutionalId: cells[columnIndex.institutional_id] ?? "",
    displayName: cells[columnIndex.display_name] ?? "",
    classCode: cells[columnIndex.class_code] ?? "",
    subjectCode: cells[columnIndex.subject_code] ?? "",
  }));

  return { ok: true, rows: parsed };
}

export function validateRowFields(row: ParsedCsvRow): ImportErrorDetail | null {
  if (!validateInstitutionalId(row.institutionalId)) {
    return {
      rowNumber: row.rowNumber,
      errorCode: ErrorCode.InvalidInstitutionalId,
      message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.InvalidInstitutionalId],
    };
  }
  if (!validateDisplayName(row.displayName)) {
    return {
      rowNumber: row.rowNumber,
      errorCode: RosterRowErrorCode.InvalidDisplayName,
      message: ROSTER_ROW_ERROR_MESSAGES[RosterRowErrorCode.InvalidDisplayName],
    };
  }
  return null;
}
