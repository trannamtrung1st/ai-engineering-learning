import { Link, useParams } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ReportSummaryCards } from "@/components/domain/reports/report-summary-cards";
import { PageHeader } from "@/components/layout/page-header";
import { ReportSessionRosterTable } from "@/components/instructor/report-session-roster-table";
import { useSessionReport } from "@/hooks/use-session-report";
import { reportCopy } from "@/lib/copy/report-labels";
import { formatReportDateVi } from "@/lib/report-date-defaults";

function RosterSkeleton() {
  return (
    <div data-testid="session-report-loading" aria-busy="true">
      <Skeleton className="mb-4 h-20 w-full" />
      <Skeleton className="h-48 w-full" />
    </div>
  );
}

/** FR-12 / AC-12 — per-session report drill-down from /reports */
export function SessionReportPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const reportQuery = useSessionReport(sessionId);

  const accessDenied =
    reportQuery.isError &&
    (reportQuery.error as Error & { errorBody?: { errorCode?: string } })?.errorBody
      ?.errorCode === "ReportAccessDenied";

  if (accessDenied) {
    return (
      <div data-testid="session-report-page">
        <PageHeader title={reportCopy.sessionReportTitle} />
        <Alert variant="danger" title={reportCopy.reportAccessDenied}>
          <p>{reportCopy.reportAccessDenied}</p>
        </Alert>
        <Link to="/reports" className="mt-4 inline-block text-primary-600 hover:underline">
          {reportCopy.sessionReportBack}
        </Link>
      </div>
    );
  }

  if (reportQuery.isLoading) {
    return (
      <div data-testid="session-report-page">
        <PageHeader title={reportCopy.sessionReportTitle} />
        <RosterSkeleton />
      </div>
    );
  }

  if (reportQuery.isError || !reportQuery.data) {
    return (
      <div data-testid="session-report-page">
        <PageHeader title={reportCopy.sessionReportTitle} />
        <Alert variant="danger" title={reportCopy.loadError}>
          <p className="mb-3">{reportCopy.loadErrorDetail}</p>
          <Button type="button" size="sm" variant="outline" onClick={() => void reportQuery.refetch()}>
            {reportCopy.retry}
          </Button>
        </Alert>
        <Link to="/reports" className="mt-4 inline-block text-primary-600 hover:underline">
          {reportCopy.sessionReportBack}
        </Link>
      </div>
    );
  }

  const report = reportQuery.data;
  const sessionDate = formatReportDateVi(report.scheduledStart);
  const enrolled = report.summary.enrolled;
  const avgRate = enrolled > 0 ? `${Math.round((report.summary.present / enrolled) * 100)}%` : "0%";

  return (
    <div data-testid="session-report-page">
      <PageHeader
        title={reportCopy.sessionReportTitle}
        description={`${report.classCode} · ${report.subjectCode} · ${sessionDate}`}
        actions={
          <Link
            to="/reports"
            className="inline-flex min-h-touch items-center text-primary-600 hover:underline"
          >
            {reportCopy.sessionReportBack}
          </Link>
        }
      />
      <ReportSummaryCards
        totalSessions={1}
        avgAttendance={avgRate}
        totalAbsent={report.summary.absent}
        totalExcused={report.summary.excused}
      />
      <ReportSessionRosterTable records={report.records} />
    </div>
  );
}
