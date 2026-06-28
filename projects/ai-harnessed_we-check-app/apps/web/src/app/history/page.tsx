import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AttendanceStatus } from "@wecheck/domain";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { History } from "lucide-react";

const demoRecords = [
  { id: "1", subject: "SWE-101", date: "29/06/2026", status: AttendanceStatus.Present },
  { id: "2", subject: "DB-201", date: "28/06/2026", status: AttendanceStatus.Absent },
  { id: "3", subject: "NET-301", date: "27/06/2026", status: AttendanceStatus.Excused },
];

/** NFR-17 / FR-14 — student attendance history shell */
export function HistoryPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "populated";
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  if (view === "loading") {
    return (
      <div className="flex flex-col gap-3 py-4">
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-20 w-full" />
      </div>
    );
  }

  if (view === "empty") {
    return (
      <EmptyState
        icon={History}
        title="Chưa có buổi học nào"
        description="Lịch sử điểm danh sẽ hiển thị tại đây sau khi bạn tham gia buổi học."
      />
    );
  }

  if (view === "error") {
    return (
      <Alert variant="danger" title="Không thể tải dữ liệu">
        <p className="mb-3">Đã xảy ra lỗi khi tải lịch sử điểm danh.</p>
        <Button type="button" size="sm" variant="outline">
          Thử lại
        </Button>
      </Alert>
    );
  }

  const hasMore = page < 2;

  return (
    <div className="flex flex-col gap-3 py-4" data-testid="history-page">
      {demoRecords.map((record) => (
        <div
          key={record.id}
          className="flex items-center justify-between rounded-md border border-border bg-surface-raised p-4"
        >
          <div>
            <p className="font-medium">{record.subject}</p>
            <p className="text-small text-text-secondary">{record.date}</p>
          </div>
          <StatusBadge status={record.status} />
        </div>
      ))}

      {hasMore ? (
        <Button
          type="button"
          variant="outline"
          loading={loading}
          onClick={() => {
            setLoading(true);
            setTimeout(() => {
              setLoading(false);
              setPage(2);
            }, 500);
          }}
        >
          Tải thêm
        </Button>
      ) : (
        <p className="text-center text-small text-text-secondary">Đã hiển thị tất cả</p>
      )}
    </div>
  );
}
