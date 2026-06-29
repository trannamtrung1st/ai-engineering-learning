import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Upload } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { PageHeader } from "@/components/layout/page-header";

/** NFR-17 / FR-03 — admin roster CSV import shell */
export function RosterImportPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "idle";
  const [fileName, setFileName] = useState<string | null>(null);

  if (view === "parsing") {
    return (
      <div className="flex flex-col items-center gap-4 py-12" data-testid="roster-import-page">
        <Spinner className="h-10 w-10" />
        <p className="text-body">Đang đọc tệp…</p>
      </div>
    );
  }

  if (view === "error") {
    return (
      <div data-testid="roster-import-page">
        <PageHeader title="Nhập danh sách lớp" />
        <Alert variant="danger" title="Tệp không đúng định dạng">
          Tệp CSV phải có các cột: mã sinh viên, họ tên, mã lớp, mã môn học.
        </Alert>
      </div>
    );
  }

  if (view === "complete") {
    return (
      <div data-testid="roster-import-page">
        <PageHeader title="Nhập danh sách lớp" />
        <Alert variant="success" title="Hoàn tất nhập">
          Đã nhập 42 dòng; 3 dòng lỗi
        </Alert>
      </div>
    );
  }

  return (
    <div data-testid="roster-import-page">
      <PageHeader title="Nhập danh sách lớp" />
      <label
        htmlFor="csv-upload"
        className="flex cursor-pointer flex-col items-center gap-4 rounded-md border-2 border-dashed border-border bg-surface-raised p-12 hover:border-primary-500"
      >
        <Upload className="h-12 w-12 text-text-secondary" />
        <p className="text-body text-text-secondary">
          Kéo thả tệp CSV hoặc nhấn để chọn
        </p>
        <input
          id="csv-upload"
          type="file"
          accept=".csv"
          className="sr-only"
          onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
        />
      </label>
      {fileName ? (
        <p className="mt-4 text-body">
          Đã chọn: <span className="font-medium">{fileName}</span>
        </p>
      ) : null}
      <Button type="button" className="mt-4" disabled={!fileName}>
        Xem trước
      </Button>
    </div>
  );
}
