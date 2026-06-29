import type { AttendanceStatus } from "@wecheck/domain";
import { StatusBadge } from "@/components/ui/status-badge";
import { reportCopy } from "@/lib/copy/report-labels";
import { formatMonitorTimestamp } from "@/lib/session-monitor-roster";
import type { SessionReportRecord } from "@/lib/reports-api";

export interface ReportSessionRosterTableProps {
  records: SessionReportRecord[];
}

/** FR-12 / AC-12 — read-only per-session roster for report drill-down */
export function ReportSessionRosterTable({ records }: ReportSessionRosterTableProps) {
  return (
    <div
      className="overflow-x-auto rounded-md border border-border"
      data-testid="report-session-roster-table"
    >
      <table className="w-full min-w-[640px] text-left text-body">
        <thead className="border-b border-border bg-surface-raised">
          <tr>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colStudentId}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {reportCopy.colStudentName}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Trạng thái
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              Thời gian điểm danh
            </th>
          </tr>
        </thead>
        <tbody>
          {records.map((row) => (
            <tr
              key={row.institutionalId}
              className="border-b border-border last:border-0"
            >
              <td className="px-4 py-3">{row.institutionalId}</td>
              <td className="px-4 py-3">{row.displayName}</td>
              <td className="px-4 py-3">
                <StatusBadge status={row.status as AttendanceStatus} />
              </td>
              <td className="px-4 py-3">
                {row.checkedInAt ? formatMonitorTimestamp(row.checkedInAt) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
