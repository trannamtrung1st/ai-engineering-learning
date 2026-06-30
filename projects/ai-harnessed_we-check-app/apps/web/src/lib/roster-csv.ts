/** FR-03 — client-side CSV preview parsing (mirrors server column names) */
export const REQUIRED_CSV_COLUMNS = [
  "institutional_id",
  "display_name",
  "class_code",
  "subject_code",
] as const;

export const MAX_CSV_BYTES = 5 * 1024 * 1024;
export const CSV_PREVIEW_ROW_LIMIT = 10;

export interface CsvPreviewRow {
  rowNumber: number;
  institutionalId: string;
  displayName: string;
  classCode: string;
  subjectCode: string;
}

export interface CsvPreviewResult {
  ok: true;
  rows: CsvPreviewRow[];
  totalDataRows: number;
  headers: string[];
}

export interface CsvPreviewError {
  ok: false;
  missingColumns: string[];
}

export type ParseCsvPreviewOutcome = CsvPreviewResult | CsvPreviewError;

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

/** Parse CSV text for local preview before API dry-run */
export function parseCsvPreview(
  text: string,
  maxRows = CSV_PREVIEW_ROW_LIMIT,
): ParseCsvPreviewOutcome {
  const lines = text
    .replace(/^\uFEFF/, "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

  if (lines.length === 0) {
    return { ok: false, missingColumns: [...REQUIRED_CSV_COLUMNS] };
  }

  const rawHeaders = parseCsvLine(lines[0]!);
  const headers = rawHeaders.map(normalizeHeader);
  const missingColumns = REQUIRED_CSV_COLUMNS.filter((col) => !headers.includes(col));

  if (missingColumns.length > 0) {
    return { ok: false, missingColumns: [...missingColumns] };
  }

  const colIndex = Object.fromEntries(
    REQUIRED_CSV_COLUMNS.map((col) => [col, headers.indexOf(col)]),
  ) as Record<(typeof REQUIRED_CSV_COLUMNS)[number], number>;

  const dataLines = lines.slice(1);
  const rows: CsvPreviewRow[] = [];

  for (let i = 0; i < dataLines.length && rows.length < maxRows; i += 1) {
    const fields = parseCsvLine(dataLines[i]!);
    rows.push({
      rowNumber: i + 2,
      institutionalId: fields[colIndex.institutional_id] ?? "",
      displayName: fields[colIndex.display_name] ?? "",
      classCode: fields[colIndex.class_code] ?? "",
      subjectCode: fields[colIndex.subject_code] ?? "",
    });
  }

  return {
    ok: true,
    rows,
    totalDataRows: dataLines.length,
    headers: rawHeaders,
  };
}

export function validateCsvFileSelection(file: File | null): string | null {
  if (!file) return "Chưa chọn tệp";
  if (!file.name.toLowerCase().endsWith(".csv")) {
    return "Chỉ chấp nhận tệp .csv";
  }
  if (file.size > MAX_CSV_BYTES) {
    return "Tệp vượt quá 5 MB";
  }
  return null;
}
