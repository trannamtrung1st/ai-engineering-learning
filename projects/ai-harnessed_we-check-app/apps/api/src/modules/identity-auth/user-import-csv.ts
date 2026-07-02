import { ErrorCode, UserRole } from "@wecheck/domain";
import type { UserImportErrorDetail, ParsedUserCsvRow } from "./user-import-types.js";

export const USER_REQUIRED_CSV_COLUMNS = [
  "institutional_id",
  "display_name",
  "email",
  "role",
  "active",
] as const;

const INSTITUTIONAL_ID_RE = /^[A-Za-z0-9\-_.]{3,32}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_FILE_BYTES = 5 * 1024 * 1024;
const USER_ROLES = new Set<string>(Object.values(UserRole));

export function validateUserCsvFile(
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

export function parseUserCsvContent(content: string): {
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

export function validateUserInstitutionalId(value: string): boolean {
  return INSTITUTIONAL_ID_RE.test(value.trim());
}

export function validateUserDisplayName(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length >= 1 && trimmed.length <= 200;
}

export function normalizeUserEmail(email: string): string {
  return email.trim().toLowerCase();
}

export function validateUserEmail(value: string): boolean {
  const normalized = normalizeUserEmail(value);
  return normalized.length > 0 && normalized.length <= 254 && EMAIL_RE.test(normalized);
}

export function parseUserActive(value: string): boolean | null {
  const normalized = value.trim().toLowerCase();
  if (normalized === "true" || normalized === "1") {
    return true;
  }
  if (normalized === "false" || normalized === "0") {
    return false;
  }
  return null;
}

export function mapUserCsvRows(
  headers: string[],
  rows: string[][],
): { ok: true; rows: ParsedUserCsvRow[] } | { ok: false; errors: UserImportErrorDetail[] } {
  const missingColumns = USER_REQUIRED_CSV_COLUMNS.filter(
    (col) => !headers.includes(col),
  );
  if (missingColumns.length > 0) {
    const errors: UserImportErrorDetail[] = rows.map((_, index) => ({
      rowNumber: index + 2,
      errorCode: "MissingColumns",
      message: "Thiếu cột bắt buộc trong file CSV",
    }));
    return { ok: false, errors };
  }

  const columnIndex = Object.fromEntries(
    USER_REQUIRED_CSV_COLUMNS.map((col) => [col, headers.indexOf(col)]),
  ) as Record<(typeof USER_REQUIRED_CSV_COLUMNS)[number], number>;

  const parsed: ParsedUserCsvRow[] = rows.map((cells, index) => {
    const roleRaw = cells[columnIndex.role] ?? "";
    const activeRaw = cells[columnIndex.active] ?? "";
    const active = parseUserActive(activeRaw);
    const role = USER_ROLES.has(roleRaw.trim())
      ? (roleRaw.trim() as UserRole)
      : (roleRaw.trim() as UserRole);
    return {
      rowNumber: index + 2,
      institutionalId: cells[columnIndex.institutional_id] ?? "",
      displayName: cells[columnIndex.display_name] ?? "",
      email: cells[columnIndex.email] ?? "",
      role,
      active: active ?? false,
      rawRole: roleRaw,
      rawActive: activeRaw,
    };
  });

  return { ok: true, rows: parsed };
}

export function validateUserImportRow(row: ParsedUserCsvRow): UserImportErrorDetail | null {
  if (!validateUserInstitutionalId(row.institutionalId)) {
    return {
      rowNumber: row.rowNumber,
      field: "institutional_id",
      errorCode: ErrorCode.InvalidInstitutionalId,
      message: "Mã định danh không hợp lệ",
    };
  }
  if (!validateUserDisplayName(row.displayName)) {
    return {
      rowNumber: row.rowNumber,
      field: "display_name",
      errorCode: ErrorCode.InvalidLength,
      message: "Độ dài dữ liệu không hợp lệ",
    };
  }
  if (!validateUserEmail(row.email)) {
    return {
      rowNumber: row.rowNumber,
      field: "email",
      errorCode: ErrorCode.InvalidEmail,
      message: "Email không hợp lệ",
    };
  }
  if (!USER_ROLES.has(row.rawRole.trim())) {
    return {
      rowNumber: row.rowNumber,
      field: "role",
      errorCode: ErrorCode.InvalidEnum,
      message: "Giá trị enum không hợp lệ",
    };
  }
  if (parseUserActive(row.rawActive) === null) {
    return {
      rowNumber: row.rowNumber,
      field: "active",
      errorCode: ErrorCode.InvalidEnum,
      message: "Giá trị enum không hợp lệ",
    };
  }
  return null;
}
