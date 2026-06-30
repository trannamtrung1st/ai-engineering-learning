import { useMemo, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AdminReportFilterBar } from "@/components/admin/admin-report-filter-bar";
import { ReportSummaryCards } from "@/components/domain/reports/report-summary-cards";
import {
  SessionReportTable,
  type SessionReportRow,
} from "@/components/domain/reports/session-report-table";
import { StudentSummaryTable } from "@/components/instructor/student-summary-table";
import { PageHeader } from "@/components/layout/page-header";
import { useReportSessions } from "@/hooks/use-report-sessions";
import { useReportSummary } from "@/hooks/use-report-summary";
import { reportCopy } from "@/lib/copy/report-labels";
import { formatAttendanceRate, formatReportDateVi } from "@/lib/report-date-defaults";
import type { ReportFilterParams } from "@/lib/reports-api";

function SummarySkeleton() {
  return (
    <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="report-summary-loading">
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
    </div>
  );
}

function computeSummaryCardMetrics(
  summary: NonNullable<ReturnType<typeof useReportSummary>["data"]>,
) {
  const students = summary.students;
  const totalAbsent = students.reduce((sum, row) => sum + row.absentCount, 0);
  const totalExcused = students.reduce((sum, row) => sum + row.excusedCount, 0);
  const avgAttendance =
    students.length > 0
      ? formatAttendanceRate(
          students.reduce((sum, row) => sum + row.attendanceRate, 0) / students.length,
        )
      : "0%";

  return {
    totalSessions: summary.sessionsHeld,
    avgAttendance,
    totalAbsent,
    totalExcused,
  };
}

/** NFR-17 / FR-12 / AC-12 — admin institution-wide reports */
export function AdminReportsPage() {
  const [appliedFilters, setAppliedFilters] = useState<ReportFilterParams | null>(null);
  const summaryQuery = useReportSummary(appliedFilters);
  const sessionsQuery = useReportSessions(appliedFilters);

  const sessionRows = useMemo((): SessionReportRow[] => {
    const items = sessionsQuery.data?.items ?? [];
    return items.map((session) => {
      const enrolled = session.enrolled || session.present + session.absent + session.excused;
      const rate = enrolled > 0 ? session.present / enrolled : 0;
      return {
        sessionId: session.sessionId,
        date: formatReportDateVi(session.scheduledStart),
        classCode: session.classCode,
        subjectCode: session.subjectCode,
        attendanceRate: formatAttendanceRate(rate),
        present: session.present,
        absent: session.absent,
      };
    });
  }, [sessionsQuery.data?.items]);

  const showInitial = appliedFilters === null;
  const showEmpty =
    appliedFilters !== null &&
    summaryQuery.isSuccess &&
    summaryQuery.data.students.length === 0 &&
    sessionRows.length === 0;
  const showError =
    appliedFilters !== null &&
    (summaryQuery.isError || sessionsQuery.isError) &&
  !summaryQuery.isLoading &&
  !sessionsQuery.isLoading;
  const showResults =
    appliedFilters !== null &&
    summaryQuery.isSuccess &&
    !showEmpty &&
    !showError;
  const isLoading =
    appliedFilters !== null && (summaryQuery.isLoading || sessionsQuery.isLoading);

  return (
    <div data-testid="admin-reports-page">
      <PageHeader title={reportCopy.adminPageTitle} description={reportCopy.adminPageDescription} />
      <AdminReportFilterBar
        showAllClasses
        idPrefix="admin-report"
        onApply={setAppliedFilters}
        disabled={summaryQuery.isFetching || sessionsQuery.isFetching}
      />

      {showInitial ? (
        <p className="text-body text-text-secondary">{reportCopy.filterPrompt}</p>
      ) : null}

      {isLoading ? <SummarySkeleton /> : null}

      {showEmpty ? (
        <p className="text-body text-text-secondary">{reportCopy.emptyResults}</p>
      ) : null}

      {showError ? (
        <Alert variant="danger" title={reportCopy.loadError}>
          <p className="mb-3">{reportCopy.loadErrorDetail}</p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              void summaryQuery.refetch();
              void sessionsQuery.refetch();
            }}
          >
            {reportCopy.retry}
          </Button>
        </Alert>
      ) : null}

      {showResults && summaryQuery.data ? (
        <>
          <ReportSummaryCards {...computeSummaryCardMetrics(summaryQuery.data)} />
          <StudentSummaryTable rows={summaryQuery.data.students} />
          <SessionReportTable rows={sessionRows} />
        </>
      ) : null}
    </div>
  );
}
