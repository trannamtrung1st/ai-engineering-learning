import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";

/** NFR-17 / FR-13 — admin CSV export shell */
export function AdminExportPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "ready";
  const [exporting, setExporting] = useState(false);

  if (view === "forbidden") {
    return (
      <div data-testid="admin-export-page">
        <Alert variant="danger">
          Chỉ phòng đào tạo mới có quyền xuất dữ liệu
        </Alert>
      </div>
    );
  }

  if (view === "denied") {
    return <ForbiddenPage />;
  }

  if (view === "error") {
    return (
      <div data-testid="admin-export-page">
        <PageHeader title="Xuất CSV" />
        <Alert variant="danger" title="Xuất thất bại">
          <p className="mb-3">Không thể tạo tệp xuất. Vui lòng thử lại.</p>
          <Button type="button" size="sm" variant="outline">
            Thử lại
          </Button>
        </Alert>
      </div>
    );
  }

  function handleExport() {
    setExporting(true);
    setTimeout(() => {
      setExporting(false);
      toast.success("Đã tải xuống");
    }, 1000);
  }

  return (
    <div data-testid="admin-export-page">
      <PageHeader title="Xuất CSV" description="Xuất dữ liệu điểm danh theo bộ lọc" />
      <div className="rounded-md border border-border bg-surface-raised p-6">
        <div className="mb-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-small font-medium" htmlFor="export-class">
              Lớp
            </label>
            <select id="export-class" className="mt-1 w-full rounded-md border border-border p-2">
              <option>Tất cả</option>
            </select>
          </div>
          <div>
            <label className="text-small font-medium" htmlFor="export-from">
              Từ ngày
            </label>
            <input id="export-from" type="date" className="mt-1 w-full rounded-md border border-border p-2" />
          </div>
        </div>
        <Button type="button" loading={exporting} onClick={handleExport}>
          Xuất CSV
        </Button>
        {exporting ? (
          <div className="mt-4 flex items-center gap-2">
            <Spinner className="h-5 w-5" />
            <span className="text-body text-text-secondary">Đang tạo tệp…</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
