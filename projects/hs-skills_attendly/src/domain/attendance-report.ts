import { and, eq, lte } from "drizzle-orm";
import { randomUUID } from "node:crypto";
import type { AttendlyDatabase } from "../db/client";
import {
  attendanceRecords,
  auditLogs,
  classSections,
  classSessions,
  enrollments,
  users,
} from "../db/schema";

export const ATTENDANCE_STATUSES = [
  "present",
  "late",
  "absent",
  "excused",
  "manual_present",
] as const;

export type AttendanceStatus = (typeof ATTENDANCE_STATUSES)[number];

export type StatusTotals = Record<AttendanceStatus, number>;

export type StudentSessionEntry = {
  classSessionId: string;
  startsAt: Date;
  status: AttendanceStatus | null;
};

export type StudentSectionHistory = {
  classSectionId: string;
  sectionName: string;
  sessions: StudentSessionEntry[];
  totals: StatusTotals;
};

function emptyTotals(): StatusTotals {
  return {
    present: 0,
    late: 0,
    absent: 0,
    excused: 0,
    manual_present: 0,
  };
}

export function getStudentAttendanceHistory(
  db: AttendlyDatabase,
  input: { studentId: string; now?: Date },
): StudentSectionHistory[] {
  const now = input.now ?? new Date();

  const sections = db
    .select({
      classSectionId: classSections.id,
      sectionName: classSections.name,
    })
    .from(enrollments)
    .innerJoin(classSections, eq(enrollments.classSectionId, classSections.id))
    .where(eq(enrollments.studentId, input.studentId))
    .all();

  return sections.map((section) => {
    const sessions = db
      .select({
        classSessionId: classSessions.id,
        startsAt: classSessions.startsAt,
        status: attendanceRecords.status,
      })
      .from(classSessions)
      .leftJoin(
        attendanceRecords,
        and(
          eq(attendanceRecords.classSessionId, classSessions.id),
          eq(attendanceRecords.studentId, input.studentId),
        ),
      )
      .where(
        and(
          eq(classSessions.classSectionId, section.classSectionId),
          lte(classSessions.startsAt, now),
        ),
      )
      .orderBy(classSessions.startsAt)
      .all();

    const totals = emptyTotals();
    for (const session of sessions) {
      if (session.status) totals[session.status] += 1;
    }

    return { ...section, sessions, totals };
  });
}

export type SectionReportRow = {
  studentId: string;
  studentName: string;
  counts: StatusTotals;
  /** (present + late + manual_present + excused) / resolved sessions; null when nothing is resolved yet */
  attendanceRate: number | null;
};

export type SectionReport = {
  classSectionId: string;
  sectionName: string;
  rows: SectionReportRow[];
};

export class AttendanceReportError extends Error {
  constructor(public readonly code: "section_not_found" | "not_owner") {
    super(code);
  }
}

export function getSectionReport(
  db: AttendlyDatabase,
  input: { classSectionId: string; lecturerId: string },
): SectionReport {
  const section = db
    .select({
      id: classSections.id,
      name: classSections.name,
      lecturerId: classSections.lecturerId,
    })
    .from(classSections)
    .where(eq(classSections.id, input.classSectionId))
    .get();
  if (!section) throw new AttendanceReportError("section_not_found");
  if (section.lecturerId !== input.lecturerId) {
    throw new AttendanceReportError("not_owner");
  }

  const students = db
    .select({ studentId: users.id, studentName: users.name })
    .from(enrollments)
    .innerJoin(users, eq(enrollments.studentId, users.id))
    .where(eq(enrollments.classSectionId, section.id))
    .orderBy(users.name)
    .all();

  const records = db
    .select({
      studentId: attendanceRecords.studentId,
      status: attendanceRecords.status,
    })
    .from(attendanceRecords)
    .innerJoin(
      classSessions,
      eq(attendanceRecords.classSessionId, classSessions.id),
    )
    .where(eq(classSessions.classSectionId, section.id))
    .all();

  const countsByStudent = new Map<string, StatusTotals>(
    students.map(({ studentId }) => [studentId, emptyTotals()]),
  );
  for (const record of records) {
    const counts = countsByStudent.get(record.studentId);
    if (counts) counts[record.status] += 1;
  }

  const rows = students.map(({ studentId, studentName }) => {
    const counts = countsByStudent.get(studentId)!;
    const resolved =
      counts.present +
      counts.late +
      counts.absent +
      counts.excused +
      counts.manual_present;
    const attended = resolved - counts.absent;
    return {
      studentId,
      studentName,
      counts,
      attendanceRate: resolved === 0 ? null : attended / resolved,
    };
  });

  return { classSectionId: section.id, sectionName: section.name, rows };
}

export function csvEscape(value: string) {
  // Neutralize spreadsheet formula injection: a leading =, +, -, @, tab, or CR
  // makes Excel/Sheets evaluate the cell as a formula, so prefix such values
  // with a single quote before applying normal CSV quoting.
  const guarded = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n]/.test(guarded) ? `"${guarded.replaceAll('"', '""')}"` : guarded;
}

export function exportSectionReportCsv(
  db: AttendlyDatabase,
  input: { classSectionId: string; lecturerId: string; now?: Date },
): { csv: string; auditLogId: string } {
  const now = input.now ?? new Date();
  const report = getSectionReport(db, input);

  const header = [
    "student_id",
    "student_name",
    "present",
    "late",
    "absent",
    "excused",
    "manual_present",
    "attendance_rate",
  ];
  const lines = [header.join(",")];
  for (const row of report.rows) {
    lines.push(
      [
        csvEscape(row.studentId),
        csvEscape(row.studentName),
        String(row.counts.present),
        String(row.counts.late),
        String(row.counts.absent),
        String(row.counts.excused),
        String(row.counts.manual_present),
        row.attendanceRate === null ? "" : row.attendanceRate.toFixed(2),
      ].join(","),
    );
  }
  const csv = `${lines.join("\n")}\n`;

  const auditLogId = randomUUID();
  db.insert(auditLogs)
    .values({
      id: auditLogId,
      actorId: input.lecturerId,
      attendanceRecordId: null,
      action: "attendance.report_exported",
      oldValue: null,
      newValue: JSON.stringify({
        classSectionId: report.classSectionId,
        sectionName: report.sectionName,
        rowCount: report.rows.length,
      }),
      reason: "Section attendance report CSV export",
      createdAt: now,
    })
    .run();

  return { csv, auditLogId };
}
