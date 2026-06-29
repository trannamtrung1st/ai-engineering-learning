import { ChevronDown, ChevronUp, Download, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { rosterCopy, ROSTER_CSV_TEMPLATE } from "@/lib/copy/roster-labels";
import {
  type ImportBatchDto,
  pollImportBatchUntilComplete,
  postRosterImport,
} from "@/lib/roster-api";
import {
  parseCsvPreview,
  validateCsvFileSelection,
  type CsvPreviewRow,
} from "@/lib/roster-csv";

type ImportPhase = "select" | "preview" | "importing" | "complete";

function downloadCsvTemplate() {
  const blob = new Blob([ROSTER_CSV_TEMPLATE], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "roster-template.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function ImportErrorList({ errors }: { errors: ImportBatchDto["errorDetails"] }) {
  const [expanded, setExpanded] = useState(false);

  if (errors.length === 0) return null;

  return (
    <div className="mt-4" data-testid="roster-import-error-list">
      <Button
        type="button"
        variant="ghost"
        className="px-0"
        data-testid="roster-import-error-toggle"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? (
          <ChevronUp className="mr-1 h-4 w-4" aria-hidden="true" />
        ) : (
          <ChevronDown className="mr-1 h-4 w-4" aria-hidden="true" />
        )}
        {expanded ? rosterCopy.errorListHide : rosterCopy.errorListToggle}
        <span className="ml-1 text-text-secondary">({errors.length})</span>
      </Button>
      {expanded ? (
        <ul className="mt-2 space-y-1 rounded-md border border-border bg-surface-raised p-3 text-small">
          {errors.map((err) => (
            <li
              key={`${err.rowNumber}-${err.errorCode}`}
              data-testid={`roster-import-error-row-${err.rowNumber}`}
            >
              {rosterCopy.errorRowLabel(err.rowNumber, err.message)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PreviewTable({ rows }: { rows: CsvPreviewRow[] }) {
  return (
    <div
      className="mt-4 overflow-x-auto rounded-md border border-border"
      data-testid="roster-import-preview-table"
    >
      <table className="w-full min-w-[560px] text-left text-body">
        <thead className="border-b border-border bg-surface-raised text-small font-medium text-text-secondary">
          <tr>
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">{rosterCopy.colStudentId}</th>
            <th className="px-3 py-2">{rosterCopy.colStudentName}</th>
            <th className="px-3 py-2">{rosterCopy.filterClass}</th>
            <th className="px-3 py-2">{rosterCopy.filterSubject}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.rowNumber} className="border-b border-border last:border-b-0">
              <td className="px-3 py-2 text-text-secondary">{row.rowNumber}</td>
              <td className="px-3 py-2 font-mono text-small">{row.institutionalId}</td>
              <td className="px-3 py-2">{row.displayName}</td>
              <td className="px-3 py-2">{row.classCode}</td>
              <td className="px-3 py-2">{row.subjectCode}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** FR-03 / AC-03 — CSV upload, validation preview, and import summary */
export function RosterImportPanel() {
  const [phase, setPhase] = useState<ImportPhase>("select");
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [previewRows, setPreviewRows] = useState<CsvPreviewRow[]>([]);
  const [totalDataRows, setTotalDataRows] = useState(0);
  const [validation, setValidation] = useState<ImportBatchDto | null>(null);
  const [result, setResult] = useState<ImportBatchDto | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function reset() {
    setPhase("select");
    setFile(null);
    setFileName(null);
    setPreviewRows([]);
    setTotalDataRows(0);
    setValidation(null);
    setResult(null);
    setFormError(null);
    setBusy(false);
  }

  function handleFileChange(next: File | null) {
    setFormError(null);
    setValidation(null);
    setResult(null);
    setPreviewRows([]);
    const selectionError = validateCsvFileSelection(next);
    if (selectionError) {
      setFormError(selectionError);
      setFile(null);
      setFileName(null);
      return;
    }
    setFile(next);
    setFileName(next?.name ?? null);
    setPhase("select");
  }

  async function handlePreview() {
    if (!file) return;
    setFormError(null);
    setBusy(true);
    setPhase("preview");

    try {
      const text = await file.text();
      const parsed = parseCsvPreview(text);
      if (!parsed.ok) {
        setFormError(rosterCopy.invalidFileMessage);
        setPhase("select");
        return;
      }

      setPreviewRows(parsed.rows);
      setTotalDataRows(parsed.totalDataRows);

      const dryRun = await postRosterImport(file, { dryRun: true });
      if (!dryRun.ok) {
        setFormError(dryRun.error.message ?? rosterCopy.invalidFileApi);
        setPhase("select");
        return;
      }

      const polled = await pollImportBatchUntilComplete(dryRun.data.batchId);
      if (!polled.ok) {
        setFormError(polled.error.message ?? rosterCopy.loadError);
        setPhase("select");
        return;
      }

      setValidation(polled.data);
    } finally {
      setBusy(false);
    }
  }

  async function handleImport() {
    if (!file || !validation || validation.successRows === 0) return;
    setBusy(true);
    setPhase("importing");
    setFormError(null);

    try {
      const started = await postRosterImport(file);
      if (!started.ok) {
        setFormError(started.error.message ?? rosterCopy.loadError);
        setPhase("preview");
        return;
      }

      const completed = await pollImportBatchUntilComplete(started.data.batchId);
      if (!completed.ok) {
        setFormError(completed.error.message ?? rosterCopy.loadError);
        setPhase("preview");
        return;
      }

      setResult(completed.data);
      setPhase("complete");
      if (completed.data.errorRows === 0) {
        toast.success(rosterCopy.importSuccessToast);
      }
    } finally {
      setBusy(false);
    }
  }

  if (phase === "importing" || (phase === "preview" && busy && previewRows.length === 0)) {
    return (
      <div
        className="flex flex-col items-center gap-4 py-12"
        data-testid="roster-import-panel"
      >
        <Spinner className="h-10 w-10" />
        <p className="text-body">
          {phase === "importing" ? rosterCopy.importing : rosterCopy.validating}
        </p>
      </div>
    );
  }

  if (phase === "complete" && result) {
    const variant = result.errorRows > 0 ? "warning" : "success";
    return (
      <div data-testid="roster-import-panel">
        <div data-testid="roster-import-summary">
          <Alert variant={variant} title={rosterCopy.importCompleteTitle}>
            {rosterCopy.importCompleteSuccess(result.successRows, result.errorRows)}
          </Alert>
        </div>
        <p
          className="mt-2 text-body text-text-secondary"
          data-testid="roster-import-counts"
        >
          {rosterCopy.validationSummary(result.successRows, result.errorRows)}
        </p>
        <ImportErrorList errors={result.errorDetails} />
        <div className="mt-6 flex flex-wrap gap-3">
          <Button type="button" variant="outline" onClick={reset}>
            {rosterCopy.importAnother}
          </Button>
          <Link
            to="/admin/rosters"
            className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
            data-testid="roster-import-view-roster"
          >
            {rosterCopy.viewRosterLink}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="roster-import-panel">
      {formError ? (
        <Alert variant="danger" title={rosterCopy.invalidFileTitle} className="mb-4">
          {formError}
        </Alert>
      ) : null}

      {phase === "preview" && validation ? (
        <>
          <p className="text-body font-medium">{rosterCopy.previewTitle}</p>
          {totalDataRows > previewRows.length ? (
            <p className="mt-1 text-small text-text-secondary">
              Hiển thị {previewRows.length} / {totalDataRows} dòng
            </p>
          ) : null}
          <PreviewTable rows={previewRows} />
          <p
            className="mt-4 text-body"
            data-testid="roster-import-validation-summary"
          >
            {rosterCopy.validationSummary(validation.successRows, validation.errorRows)}
          </p>
          <ImportErrorList errors={validation.errorDetails} />
          <div className="mt-6 flex flex-wrap gap-3">
            <Button
              type="button"
              loading={busy}
              disabled={validation.successRows === 0}
              data-testid="roster-import-confirm"
              onClick={() => void handleImport()}
            >
              {rosterCopy.importConfirmButton}
            </Button>
            <Button type="button" variant="outline" onClick={reset}>
              {rosterCopy.importAnother}
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="mb-4">
            <button
              type="button"
              className="inline-flex items-center gap-2 text-small font-medium text-primary-600 hover:underline"
              data-testid="roster-csv-template-download"
              onClick={downloadCsvTemplate}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {rosterCopy.templateDownload}
            </button>
          </div>

          <label
            htmlFor="csv-upload"
            className="flex cursor-pointer flex-col items-center gap-4 rounded-md border-2 border-dashed border-border bg-surface-raised p-12 hover:border-primary-500"
          >
            <Upload className="h-12 w-12 text-text-secondary" aria-hidden="true" />
            <p className="text-body text-text-secondary">{rosterCopy.dropzoneHint}</p>
            <p className="text-small text-text-secondary">{rosterCopy.dropzoneMaxSize}</p>
            <input
              id="csv-upload"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              data-testid="roster-csv-file-input"
              onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
            />
          </label>

          {fileName ? (
            <p className="mt-4 text-body" data-testid="roster-selected-file">
              {rosterCopy.selectedFile}: <span className="font-medium">{fileName}</span>
            </p>
          ) : null}

          <Button
            type="button"
            className="mt-4"
            disabled={!file || busy}
            loading={busy}
            data-testid="roster-import-preview"
            onClick={() => void handlePreview()}
          >
            {rosterCopy.previewButton}
          </Button>
        </>
      )}
    </div>
  );
}
