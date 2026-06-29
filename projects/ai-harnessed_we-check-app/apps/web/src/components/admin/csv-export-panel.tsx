import { Download } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { reportCopy } from "@/lib/copy/report-labels";
import {
  downloadBlob,
  estimateExportRowCount,
  exportAttendanceCsv,
  type ExportFilterParams,
} from "@/lib/reports-api";

type ExportPanelState = "idle" | "estimating" | "ready" | "exporting" | "error";

export interface CsvExportPanelProps {
  filters: ExportFilterParams | null;
}

function ExportConfirmDialog({
  filters,
  rowCount,
  onCancel,
  onConfirm,
}: {
  filters: ExportFilterParams;
  rowCount: number;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="export-confirm-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      data-testid="csv-export-confirm-dialog"
    >
      <div className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg">
        <h2 id="export-confirm-title" className="text-h2 font-semibold">
          {reportCopy.exportConfirmTitle}
        </h2>
        <dl className="mt-3 space-y-1 text-body text-text-secondary">
          <div className="flex gap-2">
            <dt className="font-medium text-text-primary">{reportCopy.exportScopeClass}:</dt>
            <dd>{filters.classCode}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="font-medium text-text-primary">{reportCopy.exportScopeSubject}:</dt>
            <dd>{filters.subjectCode}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="font-medium text-text-primary">{reportCopy.exportScopeFrom}:</dt>
            <dd>{filters.from}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="font-medium text-text-primary">{reportCopy.exportScopeTo}:</dt>
            <dd>{filters.to}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="font-medium text-text-primary">{reportCopy.exportEstimateLabel}:</dt>
            <dd data-testid="export-confirm-row-count">{rowCount}</dd>
          </div>
        </dl>
        <p className="mt-3 text-small text-text-secondary">{reportCopy.exportConfirmCompliance}</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            {reportCopy.exportConfirmCancel}
          </Button>
          <Button
            type="button"
            data-testid="export-confirm-submit"
            onClick={onConfirm}
          >
            {reportCopy.exportButton}
          </Button>
        </div>
      </div>
    </div>
  );
}

/** FR-13 / AC-13 / BR-09 — admin CSV export with estimate and confirm dialog */
export function CsvExportPanel({ filters }: CsvExportPanelProps) {
  const [state, setState] = useState<ExportPanelState>("idle");
  const [rowCount, setRowCount] = useState<number | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!filters) {
      setState("idle");
      setRowCount(null);
      setErrorMessage(null);
      return;
    }

    const activeFilters = filters;
    let cancelled = false;
    async function estimate() {
      setState("estimating");
      setRowCount(null);
      setErrorMessage(null);

      const result = await estimateExportRowCount(activeFilters);
      if (cancelled) return;

      if (!result.ok) {
        setState("error");
        setErrorMessage(result.error.message ?? reportCopy.exportFailed);
        return;
      }

      setRowCount(result.data);
      setState("ready");
    }

    void estimate();
    return () => {
      cancelled = true;
    };
  }, [filters]);

  async function handleExport() {
    if (!filters || rowCount === null || rowCount <= 0) return;

    setShowConfirm(false);
    setState("exporting");
    setErrorMessage(null);

    const result = await exportAttendanceCsv(filters);
    if (!result.ok) {
      setState("error");
      setErrorMessage(result.error.message ?? reportCopy.exportFailed);
      return;
    }

    downloadBlob(result.data.blob, result.data.filename);
    toast.success(reportCopy.exportSuccess);
    setState("ready");
  }

  const exportDisabled =
    !filters || state === "estimating" || state === "exporting" || rowCount === null || rowCount <= 0;

  return (
    <div className="rounded-md border border-border bg-surface-raised p-6" data-testid="csv-export-panel">
      {state === "estimating" ? (
        <div className="mb-4 flex items-center gap-2" data-testid="csv-export-estimating">
          <Spinner className="h-5 w-5" />
          <span className="text-body text-text-secondary">{reportCopy.exportEstimateLoading}</span>
        </div>
      ) : null}

      {state === "ready" && rowCount !== null ? (
        <p className="mb-4 text-body text-text-secondary" data-testid="csv-export-row-estimate">
          {reportCopy.exportEstimateLabel}: <strong>{rowCount}</strong>
        </p>
      ) : null}

      {state === "ready" && rowCount === 0 ? (
        <Alert variant="info" className="mb-4">
          {reportCopy.exportNoRows}
        </Alert>
      ) : null}

      {state === "error" && errorMessage ? (
        <Alert variant="danger" title={reportCopy.exportFailed} className="mb-4">
          <p className="mb-3">{errorMessage}</p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              if (filters) {
                setState("estimating");
                void estimateExportRowCount(filters).then((result) => {
                  if (result.ok) {
                    setRowCount(result.data);
                    setState("ready");
                    setErrorMessage(null);
                  } else {
                    setState("error");
                    setErrorMessage(result.error.message ?? reportCopy.exportFailed);
                  }
                });
              }
            }}
          >
            {reportCopy.retry}
          </Button>
        </Alert>
      ) : null}

      <Button
        type="button"
        loading={state === "exporting"}
        disabled={exportDisabled}
        onClick={() => setShowConfirm(true)}
      >
        <Download className="mr-2 h-4 w-4" aria-hidden="true" />
        {reportCopy.exportButton}
      </Button>

      {state === "exporting" ? (
        <div className="mt-4 flex items-center gap-2">
          <Spinner className="h-5 w-5" />
          <span className="text-body text-text-secondary">{reportCopy.exportProgress}</span>
        </div>
      ) : null}

      <p className="mt-4 text-small text-text-secondary">{reportCopy.exportAuditNotice}</p>

      {showConfirm && filters && rowCount !== null && rowCount > 0 ? (
        <ExportConfirmDialog
          filters={filters}
          rowCount={rowCount}
          onCancel={() => setShowConfirm(false)}
          onConfirm={() => void handleExport()}
        />
      ) : null}
    </div>
  );
}
