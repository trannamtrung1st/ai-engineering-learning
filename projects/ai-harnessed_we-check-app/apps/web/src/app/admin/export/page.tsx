import { UserRole } from "@wecheck/domain";
import { useMemo, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { AdminReportFilterBar } from "@/components/admin/admin-report-filter-bar";
import { CsvExportPanel } from "@/components/admin/csv-export-panel";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { getRoleHome } from "@/lib/auth-redirect";
import { reportCopy } from "@/lib/copy/report-labels";
import type { ExportFilterParams, ReportFilterParams } from "@/lib/reports-api";

function toExportFilters(filters: ReportFilterParams): ExportFilterParams | null {
  if (!filters.classCode || !filters.subjectCode) {
    return null;
  }
  return {
    classCode: filters.classCode,
    subjectCode: filters.subjectCode,
    from: filters.from,
    to: filters.to,
  };
}

/** NFR-17 / FR-13 / AC-13 / BR-09 — admin CSV export with RBAC gate */
export function AdminExportPage() {
  const user = useAuthUser();
  const [appliedFilters, setAppliedFilters] = useState<ReportFilterParams | null>(null);

  const isAdmin = user.role === UserRole.TrainingOfficeAdmin;
  const exportFilters = useMemo(
    () => (appliedFilters ? toExportFilters(appliedFilters) : null),
    [appliedFilters],
  );

  if (!isAdmin) {
    return <ForbiddenPage homeTo={getRoleHome(user.role)} />;
  }

  return (
    <div data-testid="admin-export-page">
      <PageHeader title={reportCopy.exportTitle} description={reportCopy.exportDescription} />
      <AdminReportFilterBar
        idPrefix="export"
        requireClassSubject
        onApply={setAppliedFilters}
      />
      {appliedFilters === null ? (
        <p className="text-body text-text-secondary">{reportCopy.filterPrompt}</p>
      ) : exportFilters ? (
        <CsvExportPanel filters={exportFilters} />
      ) : (
        <Alert variant="info">{reportCopy.exportNoRows}</Alert>
      )}
    </div>
  );
}
