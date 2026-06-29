import { useSearchParams } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ReportFilterBar } from "@/components/domain/reports/report-filter-bar";
import { ReportSummaryCards } from "@/components/domain/reports/report-summary-cards";
import { SessionReportTable } from "@/components/domain/reports/session-report-table";
import { PageHeader } from "@/components/layout/page-header";
import { reportCopy } from "@/lib/copy/report-labels";

/** NFR-17 / FR-12 / AC-12 — admin institution-wide reports shell */
export function AdminReportsPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "populated";

  if (view === "empty") {
    return (
      <div data-testid="admin-reports-page">
        <PageHeader title={reportCopy.adminPageTitle} description={reportCopy.adminPageDescription} />
        <ReportFilterBar showAllClasses idPrefix="admin-report" />
        <p className="text-body text-text-secondary">{reportCopy.emptyResults}</p>
      </div>
    );
  }

  if (view === "error") {
    return (
      <div data-testid="admin-reports-page">
        <PageHeader title={reportCopy.adminPageTitle} description={reportCopy.adminPageDescription} />
        <ReportFilterBar showAllClasses idPrefix="admin-report" />
        <Alert variant="danger" title={reportCopy.loadError}>
          <p className="mb-3">{reportCopy.loadErrorDetail}</p>
          <Button type="button" size="sm" variant="outline">
            {reportCopy.retry}
          </Button>
        </Alert>
      </div>
    );
  }

  if (view === "initial") {
    return (
      <div data-testid="admin-reports-page">
        <PageHeader title={reportCopy.adminPageTitle} description={reportCopy.adminPageDescription} />
        <ReportFilterBar showAllClasses idPrefix="admin-report" />
        <p className="text-body text-text-secondary">{reportCopy.filterPrompt}</p>
      </div>
    );
  }

  return (
    <div data-testid="admin-reports-page">
      <PageHeader title={reportCopy.adminPageTitle} description={reportCopy.adminPageDescription} />
      <ReportFilterBar showAllClasses idPrefix="admin-report" />
      <ReportSummaryCards />
      <SessionReportTable />
    </div>
  );
}
