import { ChevronDown, ChevronUp, Download, Upload } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { userImportCopy } from "@/lib/copy/user-import-labels";
import { fetchAllInstitutionalIds } from "@/lib/users-api";
import {
  parseUserCsvPreview,
  USER_CSV_TEMPLATE,
  validateUserCsvFileSelection,
  type UserCsvPreviewRow,
} from "@/lib/user-csv";
import {
  pollUserImportBatchUntilComplete,
  postUserImport,
  type UserImportBatchDto,
} from "@/lib/user-import-api";

type ImportPhase = "select" | "preview" | "importing" | "complete";

function downloadUserCsvTemplate() {
  const blob = new Blob([USER_CSV_TEMPLATE], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "users-template.csv";
  anchor.click();
  URL.revokeObjectURL(url);
}

function ImportErrorList({ errors }: { errors: UserImportBatchDto["errorDetails"] }) {
  const [expanded, setExpanded] = useState(false);

  if (errors.length === 0) return null;

  return (
    <div className="mt-4" data-testid="user-import-error-list">
      <Button
        type="button"
        variant="ghost"
        className="px-0"
        data-testid="user-import-error-toggle"
        onClick={() => setExpanded((v) => !v)}
      >
        {expanded ? (
          <ChevronUp className="mr-1 h-4 w-4" aria-hidden="true" />
        ) : (
          <ChevronDown className="mr-1 h-4 w-4" aria-hidden="true" />
        )}
        {expanded ? userImportCopy.errorListHide : userImportCopy.errorListToggle}
        <span className="ml-1 text-text-secondary">({errors.length})</span>
      </Button>
      {expanded ? (
        <ul className="mt-2 space-y-1 rounded-md border border-border bg-surface-raised p-3 text-small">
          {errors.map((err) => (
            <li
              key={`${err.rowNumber}-${err.errorCode}`}
              data-testid={`user-import-error-row-${err.rowNumber}`}
            >
              {userImportCopy.errorRowLabel(err.rowNumber, err.message)}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function PreviewStatusBadge({ row }: { row: UserCsvPreviewRow }) {
  const label =
    row.status === "create"
      ? userImportCopy.statusCreate
      : row.status === "update"
        ? userImportCopy.statusUpdate
        : userImportCopy.statusError;

  return (
    <span
      className={
        row.status === "error"
          ? "text-danger-700"
          : row.status === "update"
            ? "text-warning-700"
            : "text-success-700"
      }
      data-testid={`user-import-row-status-${row.rowNumber}`}
    >
      {label}
    </span>
  );
}

function ImportPreviewTable({ rows }: { rows: UserCsvPreviewRow[] }) {
  return (
    <div
      className="mt-4 overflow-x-auto rounded-md border border-border"
      data-testid="user-import-preview-table"
    >
      <table className="w-full min-w-[720px] text-left text-body">
        <thead className="border-b border-border bg-surface-raised text-small font-medium text-text-secondary">
          <tr>
            <th className="px-3 py-2">#</th>
            <th className="px-3 py-2">{userImportCopy.colInstitutionalId}</th>
            <th className="px-3 py-2">{userImportCopy.colDisplayName}</th>
            <th className="px-3 py-2">{userImportCopy.colEmail}</th>
            <th className="px-3 py-2">{userImportCopy.colRole}</th>
            <th className="px-3 py-2">{userImportCopy.colActive}</th>
            <th className="px-3 py-2">{userImportCopy.colStatus}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.rowNumber} className="border-b border-border last:border-b-0">
              <td className="px-3 py-2 text-text-secondary">{row.rowNumber}</td>
              <td className="px-3 py-2 font-mono text-small">{row.institutionalId}</td>
              <td className="px-3 py-2">{row.displayName}</td>
              <td className="px-3 py-2">{row.email}</td>
              <td className="px-3 py-2">{row.role}</td>
              <td className="px-3 py-2">{row.active}</td>
              <td className="px-3 py-2">
                <PreviewStatusBadge row={row} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** FR-01 / AC-01 — CSV upload, validation preview, and import summary */
export function UserImportForm() {
  const [phase, setPhase] = useState<ImportPhase>("select");
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [previewRows, setPreviewRows] = useState<UserCsvPreviewRow[]>([]);
  const [totalDataRows, setTotalDataRows] = useState(0);
  const [validation, setValidation] = useState<UserImportBatchDto | null>(null);
  const [result, setResult] = useState<UserImportBatchDto | null>(null);
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
    const selectionError = validateUserCsvFileSelection(next);
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
      const dryRun = await postUserImport(file, { dryRun: true });
      if (!dryRun.ok) {
        setFormError(dryRun.error.message ?? userImportCopy.invalidFileApi);
        setPhase("select");
        return;
      }

      const polled = await pollUserImportBatchUntilComplete(dryRun.data.batchId);
      if (!polled.ok) {
        setFormError(polled.error.message ?? userImportCopy.loadError);
        setPhase("select");
        return;
      }

      setValidation(polled.data);

      const errorRows = new Map<number, string>();
      for (const err of polled.data.errorDetails) {
        errorRows.set(err.rowNumber, err.message);
      }

      const usersResult = await fetchAllInstitutionalIds();
      const existingIds = usersResult.ok ? usersResult.data : new Set<string>();
      if (!usersResult.ok) {
        setFormError(userImportCopy.loadError);
        setPhase("select");
        return;
      }

      const parsed = parseUserCsvPreview(text, { existingIds, errorRows });
      if (!parsed.ok) {
        setFormError(userImportCopy.invalidFileMessage);
        setPhase("select");
        return;
      }

      setPreviewRows(parsed.rows);
      setTotalDataRows(parsed.totalDataRows);
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
      const started = await postUserImport(file);
      if (!started.ok) {
        setFormError(started.error.message ?? userImportCopy.loadError);
        setPhase("preview");
        return;
      }

      const completed = await pollUserImportBatchUntilComplete(started.data.batchId);
      if (!completed.ok) {
        setFormError(completed.error.message ?? userImportCopy.loadError);
        setPhase("preview");
        return;
      }

      setResult(completed.data);
      setPhase("complete");
      if (completed.data.errorRows === 0) {
        toast.success(userImportCopy.importSuccessToast);
      }
    } finally {
      setBusy(false);
    }
  }

  if (phase === "importing" || (phase === "preview" && busy && previewRows.length === 0)) {
    return (
      <div
        className="flex flex-col items-center gap-4 py-12"
        data-testid="user-import-form"
      >
        <Spinner className="h-10 w-10" />
        <p className="text-body">
          {phase === "importing" ? userImportCopy.importing : userImportCopy.validating}
        </p>
      </div>
    );
  }

  if (phase === "complete" && result) {
    const variant = result.errorRows > 0 ? "warning" : "success";
    const created = result.createdCount ?? 0;
    const updated = result.updatedCount ?? 0;

    return (
      <div data-testid="user-import-form">
        <div data-testid="user-import-summary">
          <Alert variant={variant} title={userImportCopy.importCompleteTitle}>
            {userImportCopy.importCompleteSuccess(created, updated, result.errorRows)}
          </Alert>
        </div>
        <p
          className="mt-2 text-body text-text-secondary"
          data-testid="user-import-counts"
        >
          {userImportCopy.validationSummary(result.successRows, result.errorRows)}
        </p>
        <ImportErrorList errors={result.errorDetails} />
        <div className="mt-6 flex flex-wrap gap-3">
          <Button type="button" variant="outline" onClick={reset}>
            {userImportCopy.importAnother}
          </Button>
          <Link
            to="/admin/users"
            className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
            data-testid="user-import-view-users"
          >
            {userImportCopy.viewUsersLink}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="user-import-form">
      {formError ? (
        <Alert variant="danger" title={userImportCopy.invalidFileTitle} className="mb-4">
          {formError}
        </Alert>
      ) : null}

      {phase === "preview" && validation ? (
        <>
          <p className="text-body font-medium">{userImportCopy.previewTitle}</p>
          {totalDataRows > previewRows.length ? (
            <p className="mt-1 text-small text-text-secondary">
              Hiển thị {previewRows.length} / {totalDataRows} dòng
            </p>
          ) : null}
          <ImportPreviewTable rows={previewRows} />
          <p
            className="mt-4 text-body"
            data-testid="user-import-validation-summary"
          >
            {userImportCopy.validationSummary(validation.successRows, validation.errorRows)}
          </p>
          <ImportErrorList errors={validation.errorDetails} />
          <div className="mt-6 flex flex-wrap gap-3">
            <Button type="button" variant="outline" onClick={reset}>
              {userImportCopy.importAnother}
            </Button>
            <Button
              type="button"
              disabled={busy || validation.successRows === 0}
              loading={busy}
              data-testid="user-import-confirm"
              onClick={() => void handleImport()}
            >
              {userImportCopy.confirmButton}
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-3">
            <Button type="button" variant="outline" onClick={downloadUserCsvTemplate}>
              <Download className="mr-2 h-4 w-4" aria-hidden="true" />
              {userImportCopy.templateDownload}
            </Button>
          </div>

          <label
            htmlFor="user-import-file"
            className="flex min-h-[160px] cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed border-border bg-surface-raised p-6 hover:border-primary-400 hover:bg-surface-muted"
            data-testid="user-import-dropzone"
          >
            <Upload className="mb-2 h-8 w-8 text-text-muted" aria-hidden="true" />
            <span className="text-body font-medium">{userImportCopy.dropzoneHint}</span>
            <span className="mt-1 text-small text-text-secondary">
              {userImportCopy.dropzoneMaxSize}
            </span>
            {fileName ? (
              <span className="mt-2 text-small text-text-primary">
                {userImportCopy.selectedFile}: {fileName}
              </span>
            ) : null}
            <input
              id="user-import-file"
              type="file"
              accept=".csv,text/csv"
              className="sr-only"
              data-testid="user-import-file-select"
              onChange={(e) => handleFileChange(e.target.files?.[0] ?? null)}
            />
          </label>

          <div className="mt-4 flex flex-wrap gap-3">
            <Button
              type="button"
              disabled={!file || busy}
              loading={busy}
              data-testid="user-import-preview-button"
              onClick={() => void handlePreview()}
            >
              {userImportCopy.previewButton}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
