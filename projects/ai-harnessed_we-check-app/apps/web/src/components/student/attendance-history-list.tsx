import { AttendanceStatus } from "@wecheck/domain";
import { History } from "lucide-react";
import { useEffect } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  AttendanceHistoryError,
  useAttendanceHistory,
} from "@/hooks/use-attendance-history";
import type { AttendanceHistoryItem } from "@/lib/attendance-history-api";
import { currentPathWithSearch, loginReturnUrl } from "@/lib/auth-redirect";
import {
  formatHistoryCheckInTime,
  formatHistorySessionDate,
} from "@/lib/history-format";

function HistorySkeleton() {
  return (
    <div className="flex flex-col gap-3 py-4" aria-busy="true" data-testid="history-loading">
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
      <Skeleton className="h-20 w-full" />
    </div>
  );
}

function HistoryCard({ record }: { record: AttendanceHistoryItem }) {
  const subjectLabel = record.subject.name || record.subject.code;

  return (
    <article
      className="flex items-center justify-between rounded-md border border-border bg-surface-raised p-4"
      data-testid={`history-row-${record.sessionId}`}
    >
      <div className="min-w-0 flex-1 pr-3">
        <p className="truncate font-medium text-text-primary">{subjectLabel}</p>
        <p className="text-small text-text-secondary">
          {formatHistorySessionDate(record.sessionDate)}
        </p>
        {record.status === AttendanceStatus.Present && record.checkedInAt ? (
          <p className="text-small text-text-secondary">
            Điểm danh lúc {formatHistoryCheckInTime(record.checkedInAt)}
          </p>
        ) : null}
      </div>
      <StatusBadge status={record.status} size="sm" />
    </article>
  );
}

/** FR-14 / AC-14 — read-only paginated student attendance history */
export function AttendanceHistoryList() {
  const navigate = useNavigate();
  const location = useLocation();
  const query = useAttendanceHistory();

  useEffect(() => {
    if (!query.error || !(query.error instanceof AttendanceHistoryError)) return;
    if (query.error.status !== 401) return;
    navigate(
      loginReturnUrl(currentPathWithSearch(location), {
        sessionExpired: query.error.errorCode === "SessionExpired",
      }),
      { replace: true },
    );
  }, [query.error, navigate, location]);

  if (query.isLoading) {
    return <HistorySkeleton />;
  }

  if (query.isError) {
    const errorCode =
      query.error instanceof AttendanceHistoryError
        ? query.error.errorCode
        : undefined;

    return (
      <div data-testid={errorCode ? `history-error-${errorCode}` : "history-error"}>
        <Alert variant="danger" title="Không thể tải dữ liệu">
          <p className="mb-3">Đã xảy ra lỗi khi tải lịch sử điểm danh.</p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void query.refetch()}
          >
            Thử lại
          </Button>
        </Alert>
      </div>
    );
  }

  const records = query.data?.pages.flatMap((page) => page.items) ?? [];
  const hasMore = Boolean(query.hasNextPage);

  if (records.length === 0) {
    return (
      <div data-testid="history-empty">
        <EmptyState
          icon={History}
          title="Chưa có buổi học nào"
          description="Lịch sử điểm danh sẽ hiển thị tại đây sau khi bạn tham gia buổi học."
        />
      </div>
    );
  }

  return (
    <div
      className="flex flex-col gap-3 py-4"
      data-testid="attendance-history-list"
      aria-busy={query.isFetchingNextPage}
    >
      {records.map((record) => (
        <HistoryCard key={record.sessionId} record={record} />
      ))}

      {hasMore ? (
        <Button
          type="button"
          variant="outline"
          loading={query.isFetchingNextPage}
          onClick={() => void query.fetchNextPage()}
          data-testid="history-load-more"
        >
          Tải thêm
        </Button>
      ) : (
        <p className="text-center text-small text-text-secondary" data-testid="history-end">
          Đã hiển thị tất cả
        </p>
      )}
    </div>
  );
}
