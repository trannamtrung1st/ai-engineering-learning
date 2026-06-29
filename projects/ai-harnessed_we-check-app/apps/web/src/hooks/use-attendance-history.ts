import { useInfiniteQuery } from "@tanstack/react-query";
import {
  fetchAttendanceHistory,
  HISTORY_PAGE_SIZE,
  type AttendanceHistoryResponse,
} from "@/lib/attendance-history-api";

export class AttendanceHistoryError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly errorCode?: string,
  ) {
    super(message);
    this.name = "AttendanceHistoryError";
  }
}

async function fetchHistoryPage(
  cursor?: string,
): Promise<AttendanceHistoryResponse> {
  const result = await fetchAttendanceHistory({
    cursor,
    limit: HISTORY_PAGE_SIZE,
  });

  if (!result.ok) {
    throw new AttendanceHistoryError(
      result.error.message ?? "Không thể tải lịch sử điểm danh",
      result.status,
      result.error.errorCode,
    );
  }

  return result.data;
}

/** FR-14 / AC-14 — cursor-paginated student attendance history */
export function useAttendanceHistory() {
  return useInfiniteQuery({
    queryKey: ["attendance-history"],
    queryFn: ({ pageParam }) => fetchHistoryPage(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (lastPage) => lastPage.nextCursor ?? undefined,
  });
}
