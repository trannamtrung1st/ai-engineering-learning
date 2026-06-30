import { rosterCopy } from "@/lib/copy/roster-labels";
import type { EnrollmentDto } from "@/lib/roster-api";
import { Skeleton } from "@/components/ui/skeleton";

export interface ClassRosterTableProps {
  enrollments: EnrollmentDto[];
  loading?: boolean;
}

function formatEnrolledAt(iso: string): string {
  return new Date(iso).toLocaleDateString("vi-VN", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

/** FR-03 / AC-03 — enrolled students table for admin roster view */
export function ClassRosterTable({ enrollments, loading = false }: ClassRosterTableProps) {
  if (loading) {
    return (
      <div data-testid="class-roster-table">
        <Skeleton className="mb-2 h-10 w-full" />
        <Skeleton className="mb-2 h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-border" data-testid="class-roster-table">
      <table className="w-full min-w-[480px] text-left text-body">
        <thead className="border-b border-border bg-surface-raised text-small font-medium text-text-secondary">
          <tr>
            <th className="px-4 py-3">{rosterCopy.colStudentId}</th>
            <th className="px-4 py-3">{rosterCopy.colStudentName}</th>
            <th className="px-4 py-3">{rosterCopy.colEnrolledAt}</th>
          </tr>
        </thead>
        <tbody>
          {enrollments.map((entry) => (
            <tr
              key={entry.enrollmentId}
              className="border-b border-border last:border-b-0"
              data-testid={`roster-enrollment-${entry.student.institutionalId.toLowerCase()}`}
            >
              <td className="px-4 py-3 font-mono text-small">
                {entry.student.institutionalId}
              </td>
              <td className="px-4 py-3">{entry.student.displayName}</td>
              <td className="px-4 py-3 text-text-secondary">
                {formatEnrolledAt(entry.enrolledAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
