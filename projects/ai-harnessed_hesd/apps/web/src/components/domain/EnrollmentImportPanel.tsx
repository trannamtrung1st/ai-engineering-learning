import { useCallback, useState, type ChangeEvent } from "react";
import {
  importEnrollments,
  parseEnrollmentCsv,
  type EnrollmentImportData,
  type EnrollmentImportRejectedRow,
} from "../../lib/api/academic-api";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import formStyles from "./AcademicForm.module.css";
import styles from "./EnrollmentImportPanel.module.css";

export interface EnrollmentImportPanelProps {
  classSectionId: string;
  sectionLabel?: string;
}

async function readFileText(file: File): Promise<string> {
  if (typeof file.text === "function") {
    return file.text();
  }
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(reader.error);
    reader.readAsText(file);
  });
}

export function EnrollmentImportPanel({ classSectionId, sectionLabel }: EnrollmentImportPanelProps) {
  const [fileName, setFileName] = useState<string | null>(null);
  const [parsedRows, setParsedRows] = useState<{ studentCode: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<EnrollmentImportData | null>(null);
  const [acceptedCodes, setAcceptedCodes] = useState<string[]>([]);

  const handleFileChange = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    setError(null);
    setResult(null);
    setAcceptedCodes([]);
    if (!file) {
      setFileName(null);
      setParsedRows([]);
      return;
    }
    const text = await readFileText(file);
    const rows = parseEnrollmentCsv(text);
    setFileName(file.name);
    setParsedRows(rows);
    if (rows.length === 0) {
      setError("Tệp CSV không có dòng hợp lệ. Cần cột studentCode hoặc mã sinh viên trên mỗi dòng.");
    }
  }, []);

  async function handleImport() {
    if (parsedRows.length === 0) {
      setError("Chọn tệp CSV có ít nhất một mã sinh viên.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const response = await importEnrollments(classSectionId, parsedRows);
    setSubmitting(false);

    if (!response.ok) {
      setResult(null);
      setError(response.message);
      return;
    }

    const rejectedNumbers = new Set(response.data.rejectedRows.map((row) => row.rowNumber));
    const accepted = parsedRows
      .map((row, index) => ({ code: row.studentCode, rowNumber: index + 1 }))
      .filter((row) => !rejectedNumbers.has(row.rowNumber))
      .map((row) => row.code);

    setResult(response.data);
    setAcceptedCodes((prev) => [...new Set([...prev, ...accepted])]);
  }

  const rejectionColumns = [
    {
      id: "rowNumber",
      header: "Dòng",
      cell: (row: EnrollmentImportRejectedRow) => row.rowNumber,
    },
    {
      id: "code",
      header: "Mã lỗi",
      cell: (row: EnrollmentImportRejectedRow) => row.code,
    },
    {
      id: "message",
      header: "Mô tả",
      cell: (row: EnrollmentImportRejectedRow) => row.message,
    },
  ];

  const enrollmentColumns = [
    {
      id: "studentCode",
      header: "Mã sinh viên",
      cell: (code: string) => <strong>{code}</strong>,
    },
    {
      id: "status",
      header: "Trạng thái",
      cell: () => "Active",
    },
  ];

  return (
    <div className={styles.panel} data-testid="enrollment-import-panel">
      <FeedbackAlert variant="brand" title="Nhập danh sách đăng ký">
        {sectionLabel
          ? `Nhập sinh viên cho lớp ${sectionLabel} từ tệp CSV (cột studentCode).`
          : "Nhập sinh viên từ tệp CSV (cột studentCode)."}
      </FeedbackAlert>

      <Card elevated>
        <div className={formStyles.form}>
          <h3 className={formStyles.label}>FRM-06 · Nhập CSV đăng ký</h3>

          <label className={formStyles.field}>
            <span className={formStyles.label}>Tệp CSV</span>
            <input
              className={formStyles.input}
              type="file"
              accept=".csv,text/csv"
              aria-label="Tệp CSV"
              onChange={handleFileChange}
              disabled={submitting}
            />
            {fileName ? <p className={formStyles.helper}>{fileName} · {parsedRows.length} dòng</p> : null}
          </label>

          {error ? (
            <FeedbackAlert variant="danger" title="Không thể nhập đăng ký">
              {error}
            </FeedbackAlert>
          ) : null}

          {result ? (
            <FeedbackAlert variant="success" title="Kết quả nhập">
              Đã chấp nhận {result.acceptedRows} dòng
              {result.rejectedRows.length > 0
                ? `; từ chối ${result.rejectedRows.length} dòng.`
                : "."}
            </FeedbackAlert>
          ) : null}

          <div className={formStyles.actions}>
            <Button onClick={() => void handleImport()} disabled={submitting || parsedRows.length === 0}>
              {submitting ? "Đang nhập…" : "Nhập danh sách"}
            </Button>
          </div>
        </div>
      </Card>

      {result && result.rejectedRows.length > 0 ? (
        <section className={styles.resultSection}>
          <h4 className={styles.resultTitle}>Dòng bị từ chối</h4>
          <DataTable
            columns={rejectionColumns}
            rows={result.rejectedRows}
            rowKey={(row) => `${row.rowNumber}-${row.code}`}
            caption="Chi tiết lỗi từng dòng nhập đăng ký"
          />
        </section>
      ) : null}

      {acceptedCodes.length > 0 ? (
        <section className={styles.resultSection}>
          <h4 className={styles.resultTitle}>Sinh viên đã đăng ký</h4>
          <DataTable
            columns={enrollmentColumns}
            rows={acceptedCodes}
            rowKey={(code) => code}
            caption="Danh sách sinh viên đã nhập thành công"
          />
        </section>
      ) : null}
    </div>
  );
}
