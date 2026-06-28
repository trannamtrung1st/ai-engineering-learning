import { useSearchParams } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";

/** NFR-17 / FR-12 — instructor reports shell */
export function ReportsPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "initial";

  if (view === "forbidden") {
    return <ForbiddenPage />;
  }

  if (view === "empty") {
    return (
      <div data-testid="reports-page">
        <PageHeader title="Báo cáo điểm danh" />
        <p className="text-body text-text-secondary">
          Không có dữ liệu trong khoảng thời gian đã chọn
        </p>
      </div>
    );
  }

  if (view === "error") {
    return (
      <div data-testid="reports-page">
        <PageHeader title="Báo cáo điểm danh" />
        <Alert variant="danger" title="Không thể tải báo cáo">
          <p className="mb-3">Đã xảy ra lỗi khi tải dữ liệu.</p>
          <Button type="button" size="sm" variant="outline">
            Thử lại
          </Button>
        </Alert>
      </div>
    );
  }

  return (
    <div data-testid="reports-page">
      <PageHeader title="Báo cáo điểm danh" />
      <div className="rounded-md border border-border bg-surface-raised p-6">
        <div className="mb-4 grid gap-4 sm:grid-cols-2">
          <div>
            <label className="text-small font-medium" htmlFor="filter-class">
              Lớp
            </label>
            <select id="filter-class" className="mt-1 w-full rounded-md border border-border p-2">
              <option>HESD-01</option>
            </select>
          </div>
          <div>
            <label className="text-small font-medium" htmlFor="filter-subject">
              Môn học
            </label>
            <select id="filter-subject" className="mt-1 w-full rounded-md border border-border p-2">
              <option>SWE-101</option>
            </select>
          </div>
        </div>
        <p className="mb-4 text-body text-text-secondary">
          Chọn bộ lọc và nhấn Áp dụng
        </p>
        <Button type="button">Áp dụng</Button>
      </div>
    </div>
  );
}
