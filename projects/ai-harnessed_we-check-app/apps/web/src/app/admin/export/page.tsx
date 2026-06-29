import { UserRole } from "@wecheck/domain";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ReportFilterBar } from "@/components/domain/reports/report-filter-bar";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { reportCopy } from "@/lib/copy/report-labels";

/** NFR-17 / FR-13 / AC-13 / BR-09 — admin CSV export shell with RBAC gate */
export function AdminExportPage() {
  const user = useAuthUser();
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "ready";
  const [exporting, setExporting] = useState(false);

  const isAdmin = user.role === UserRole.TrainingOfficeAdmin;

  if (view === "denied") {
    return <ForbiddenPage />;
  }

  if (!isAdmin || view === "forbidden") {
    return (
      <div data-testid="admin-export-page">
        <Alert variant="danger">{reportCopy.exportDenied}</Alert>
      </div>
    );
  }

  if (view === "error") {
    return (
      <div data-testid="admin-export-page">
        <PageHeader title={reportCopy.exportTitle} description={reportCopy.exportDescription} />
        <Alert variant="danger" title={reportCopy.exportFailed}>
          <p className="mb-3">{reportCopy.exportFailedDetail}</p>
          <Button type="button" size="sm" variant="outline">
            {reportCopy.retry}
          </Button>
        </Alert>
      </div>
    );
  }

  function handleExport() {
    setExporting(true);
    setTimeout(() => {
      setExporting(false);
      toast.success(reportCopy.exportSuccess);
    }, 1000);
  }

  return (
    <div data-testid="admin-export-page">
      <PageHeader title={reportCopy.exportTitle} description={reportCopy.exportDescription} />
      <div className="rounded-md border border-border bg-surface-raised p-6">
        <ReportFilterBar showAllClasses idPrefix="export" />
        <Button type="button" loading={exporting} onClick={handleExport}>
          {reportCopy.exportButton}
        </Button>
        {exporting ? (
          <div className="mt-4 flex items-center gap-2">
            <Spinner className="h-5 w-5" />
            <span className="text-body text-text-secondary">{reportCopy.exportProgress}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
