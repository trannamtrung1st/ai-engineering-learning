/** FR-01 — client-side user CSV preview parsing (mirrors server column names) */
export const USER_REQUIRED_CSV_COLUMNS = [
  "institutional_id",
  "display_name",
  "email",
  "role",
  "active",
] as const;

export const USER_CSV_TEMPLATE = [
  "institutional_id,display_name,email,role,active",
  "SV2026100,Nguyễn Văn M,student100@example.edu.vn,Student,true",
].join("\n");

export const MAX_USER_CSV_BYTES = 5 * 1024 * 1024;
export const USER_CSV_PREVIEW_ROW_LIMIT = 10;

export type UserImportPreviewStatus = "create" | "update" | "error";

export interface UserCsvPreviewRow {
  rowNumber: number;
  institutionalId: string;
  displayName: string;
  email: string;
  role: string;
  active: string;
  status: UserImportPreviewStatus;
  statusMessage?: string;
}

export interface UserCsvPreviewResult {
  ok: true;
  rows: UserCsvPreviewRow[];
  totalDataRows: number;
  headers: string[];
}

export interface UserCsvPreviewError {
  ok: false;
  missingColumns: string[];
}

export type ParseUserCsvPreviewOutcome = UserCsvPreviewResult | UserCsvPreviewError;

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

function normalizeHeader(header: string): string {
  return header.trim().toLowerCase().replace(/\s+/g, "_");
}

export function parseUserCsvPreview(
  content: string,
  options?: {
    maxRows?: number;
    existingIds?: Set<string>;
    errorRows?: Map<number, string>;
  },
): ParseUserCsvPreviewOutcome {
  const maxRows = options?.maxRows ?? USER_CSV_PREVIEW_ROW_LIMIT;
  const existingIds = options?.existingIds ?? new Set<string>();
  const errorRows = options?.errorRows ?? new Map<number, string>();

  const normalized = content.replace(/^\uFEFF/, "").trim();
  if (!normalized) {
    return { ok: false, missingColumns: [...USER_REQUIRED_CSV_COLUMNS] };
  }

  const lines = normalized.split(/\r?\n/).filter((line) => line.trim().length > 0);
  if (lines.length === 0) {
    return { ok: false, missingColumns: [...USER_REQUIRED_CSV_COLUMNS] };
  }

  const rawHeaders = parseCsvLine(lines[0]!);
  const headers = rawHeaders.map(normalizeHeader);
  const missingColumns = USER_REQUIRED_CSV_COLUMNS.filter((col) => !headers.includes(col));

  if (missingColumns.length > 0) {
    return { ok: false, missingColumns: [...missingColumns] };
  }

  const colIndex = Object.fromEntries(
    USER_REQUIRED_CSV_COLUMNS.map((col) => [col, headers.indexOf(col)]),
  ) as Record<(typeof USER_REQUIRED_CSV_COLUMNS)[number], number>;

  const dataLines = lines.slice(1);
  const rows: UserCsvPreviewRow[] = [];

  for (let i = 0; i < dataLines.length && rows.length < maxRows; i += 1) {
    const fields = parseCsvLine(dataLines[i]!);
    const rowNumber = i + 2;
    const institutionalId = fields[colIndex.institutional_id] ?? "";
    const errorMessage = errorRows.get(rowNumber);

    let status: UserImportPreviewStatus;
    if (errorMessage) {
      status = "error";
    } else if (existingIds.has(institutionalId.trim())) {
      status = "update";
    } else {
      status = "create";
    }

    rows.push({
      rowNumber,
      institutionalId,
      displayName: fields[colIndex.display_name] ?? "",
      email: fields[colIndex.email] ?? "",
      role: fields[colIndex.role] ?? "",
      active: fields[colIndex.active] ?? "",
      status,
      statusMessage: errorMessage,
    });
  }

  return {
    ok: true,
    rows,
    totalDataRows: dataLines.length,
    headers: rawHeaders,
  };
}

export function validateUserCsvFileSelection(file: File | null): string | null {
  if (!file) return "Chưa chọn tệp";
  if (!file.name.toLowerCase().endsWith(".csv")) {
    return "Chỉ chấp nhận tệp .csv";
  }
  if (file.size > MAX_USER_CSV_BYTES) {
    return "Tệp vượt quá 5 MB";
  }
  return null;
}
