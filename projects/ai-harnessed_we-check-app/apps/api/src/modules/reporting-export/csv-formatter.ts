import type { CsvExportRow } from "./types.js";

export const CSV_HEADERS = [
  "institutional_id",
  "display_name",
  "class_code",
  "subject_code",
  "session_date",
  "attendance_status",
  "checked_in_at",
] as const;

function escapeCsvField(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

export function formatAttendanceCsv(rows: readonly CsvExportRow[]): string {
  const lines = [CSV_HEADERS.join(",")];
  for (const row of rows) {
    lines.push(
      [
        escapeCsvField(row.institutionalId),
        escapeCsvField(row.displayName),
        escapeCsvField(row.classCode),
        escapeCsvField(row.subjectCode),
        escapeCsvField(row.sessionDate),
        escapeCsvField(row.attendanceStatus),
        escapeCsvField(row.checkedInAt ?? ""),
      ].join(","),
    );
  }
  return `${lines.join("\n")}\n`;
}

export function exportFilename(date = new Date()): string {
  const iso = date.toISOString().slice(0, 10);
  return `attendance-export-${iso}.csv`;
}
