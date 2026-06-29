import { SessionStatus } from "@wecheck/domain";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ReportSummaryCards } from "@/components/domain/reports/report-summary-cards";
import {
  SessionReportTable,
  type SessionReportRow,
} from "@/components/domain/reports/session-report-table";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { InstructorReportFilterBar } from "@/components/instructor/instructor-report-filter-bar";
import { StudentSummaryTable } from "@/components/instructor/student-summary-table";
import { useReportSummary } from "@/hooks/use-report-summary";
import { useSessionsList } from "@/hooks/use-sessions-list";
import { reportCopy } from "@/lib/copy/report-labels";
import {
  formatAttendanceRate,
  formatReportDateVi,
  sessionDateInRange,
} from "@/lib/report-date-defaults";
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

/** FR-12 / AC-12 / BR-08 — instructor attendance reports scoped to assignments */
export function ReportsPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view");

  const [appliedFilters, setAppliedFilters] = useState<ReportFilterParams | null>(null);
  const summaryQuery = useReportSummary(appliedFilters);
  const sessionsQuery = useSessionsList();

  const sessionRows = useMemo((): SessionReportRow[] => {
    if (!appliedFilters || !summaryQuery.data) return [];
    const items = sessionsQuery.data?.items ?? [];
    return items
      .filter(
        (session) =>
          session.status === SessionStatus.Closed &&
          session.classCode === appliedFilters.classCode &&
          session.subjectCode === appliedFilters.subjectCode &&
          sessionDateInRange(
            session.scheduledStart,
            appliedFilters.from,
            appliedFilters.to,
          ),
      )
      .sort(
        (a, b) =>
          new Date(b.scheduledStart).getTime() - new Date(a.scheduledStart).getTime(),
      )
      .map((session) => {
        const present = session.presentCount ?? 0;
        const enrolled = session.enrollmentCount ?? present;
        const absent = Math.max(enrolled - present, 0);
        const rate = enrolled > 0 ? present / enrolled : 0;
        return {
          sessionId: session.id,
          date: formatReportDateVi(session.scheduledStart),
          classCode: session.classCode,
          subjectCode: session.subjectCode,
          attendanceRate: formatAttendanceRate(rate),
          present,
          absent,
        };
      });
  }, [appliedFilters, summaryQuery.data, sessionsQuery.data?.items]);

  if (view === "forbidden") {
    return <ForbiddenPage homeTo="/sessions" />;
  }

  const accessDenied =
    summaryQuery.isError &&
    (summaryQuery.error as Error & { status?: number; errorBody?: { errorCode?: string } })
      ?.errorBody?.errorCode === "ReportAccessDenied";

  if (accessDenied) {
    return (
      <div data-testid="reports-page">
        <PageHeader title={reportCopy.pageTitle} description={reportCopy.pageDescription} />
        <Alert variant="danger" title={reportCopy.reportAccessDenied}>
          <p>{reportCopy.reportAccessDenied}</p>
        </Alert>
      </div>
    );
  }

  const showInitial = appliedFilters === null && view !== "empty" && view !== "error";
  const showEmpty =
    view === "empty" ||
    (appliedFilters !== null &&
      summaryQuery.isSuccess &&
      summaryQuery.data.students.length === 0);
  const showError = view === "error" || (appliedFilters !== null && summaryQuery.isError && !accessDenied);
  const showResults = appliedFilters !== null && summaryQuery.isSuccess && !showEmpty;

  return (
    <div data-testid="reports-page">
      <PageHeader title={reportCopy.pageTitle} description={reportCopy.pageDescription} />
      <InstructorReportFilterBar
        onApply={setAppliedFilters}
        disabled={summaryQuery.isFetching}
      />

      {showInitial ? (
        <p className="text-body text-text-secondary">{reportCopy.filterPrompt}</p>
      ) : null}

      {appliedFilters !== null && summaryQuery.isLoading ? <SummarySkeleton /> : null}

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
            onClick={() => void summaryQuery.refetch()}
          >
            {reportCopy.retry}
          </Button>
        </Alert>
      ) : null}

      {showResults && summaryQuery.data ? (
        <>
          <ReportSummaryCards {...computeSummaryCardMetrics(summaryQuery.data)} />
          <StudentSummaryTable rows={summaryQuery.data.students} />
          <SessionReportTable rows={sessionRows} showSessionLinks />
        </>
      ) : null}
    </div>
  );
}
