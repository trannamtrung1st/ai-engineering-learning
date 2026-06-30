import { Link } from "react-router-dom";
import { reportCopy } from "@/lib/copy/report-labels";

export interface SessionReportRow {
  sessionId?: string;
  date: string;
  classCode: string;
  subjectCode: string;
  attendanceRate: string;
  present: number;
  absent: number;
}

export interface SessionReportTableProps {
  rows?: SessionReportRow[];
  showSessionLinks?: boolean;
}

const demoRows: SessionReportRow[] = [
  {
    date: "28/06/2026",
    classCode: "HESD-01",
    subjectCode: "SWE-101",
    attendanceRate: "92%",
    present: 46,
    absent: 4,
  },
  {
    date: "21/06/2026",
    classCode: "HESD-02",
    subjectCode: "SWE-101",
    attendanceRate: "85%",
    present: 34,
    absent: 6,
  },
];

/** FR-12 / AC-12 — session-level aggregated report table */
export function SessionReportTable({
  rows = demoRows,
  showSessionLinks = false,
}: SessionReportTableProps) {
  return (
    <div className="overflow-x-auto rounded-md border border-border" data-testid="session-report-table">
      <table className="w-full min-w-[640px] text-left text-body">
        <thead className="border-b border-border bg-surface-raised">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colDate}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colClass}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colSubject}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colAttendanceRate}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colPresent}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colAbsent}
            </th>
            {showSessionLinks ? (
              <th scope="col" className="px-4 py-3 font-medium">
                {reportCopy.colSessionDetail}
              </th>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.sessionId ?? `${row.date}-${row.classCode}`}
              className="border-b border-border last:border-0"
            >
              <td className="px-4 py-3">{row.date}</td>
              <td className="px-4 py-3">{row.classCode}</td>
              <td className="px-4 py-3">{row.subjectCode}</td>
              <td className="px-4 py-3">{row.attendanceRate}</td>
              <td className="px-4 py-3">{row.present}</td>
              <td className="px-4 py-3">{row.absent}</td>
              {showSessionLinks ? (
                <td className="px-4 py-3">
                  {row.sessionId ? (
                    <Link
                      to={`/reports/sessions/${row.sessionId}`}
                      className="font-medium text-primary-600 hover:underline"
                    >
                      {reportCopy.viewSessionReport}
                    </Link>
                  ) : (
                    "—"
                  )}
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
