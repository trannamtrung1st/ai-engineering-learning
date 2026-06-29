import { reportCopy } from "@/lib/copy/report-labels";
import { formatAttendanceRate } from "@/lib/report-date-defaults";
import type { StudentSummaryRow } from "@/lib/reports-api";

export interface StudentSummaryTableProps {
  rows: StudentSummaryRow[];
}

/** FR-12 / AC-12 — per-student attendance aggregation across date range */
export function StudentSummaryTable({ rows }: StudentSummaryTableProps) {
  return (
    <div
      className="mb-6 overflow-x-auto rounded-md border border-border"
      data-testid="student-summary-table"
    >
      <table className="w-full min-w-[720px] text-left text-body">
        <thead className="border-b border-border bg-surface-raised">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colStudentId}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colStudentName}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colPresent}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colAbsent}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colExcused}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colAttendanceRateStudent}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.institutionalId}
              className="border-b border-border last:border-0"
            >
              <td className="px-4 py-3">{row.institutionalId}</td>
              <td className="px-4 py-3">{row.displayName}</td>
              <td className="px-4 py-3">{row.presentCount}</td>
              <td className="px-4 py-3">{row.absentCount}</td>
              <td className="px-4 py-3">{row.excusedCount}</td>
              <td className="px-4 py-3">{formatAttendanceRate(row.attendanceRate)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
