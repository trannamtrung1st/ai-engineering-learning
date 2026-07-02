import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  fetchAttendanceHistory,
  groupRowsBySection,
  type AttendanceHistoryRow,
} from "../../lib/api/attendance-history-api";
import {
  DEFAULT_LISTING_QUERY,
  listingQueryToSearchParams,
  parseListingQuery,
} from "../../lib/listing/query-state";
import { formatCheckInTimestamp } from "../../lib/check-in/format-timestamp";
import { AttendanceStatusCell } from "./AttendanceStatusCell";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { Button } from "../ui/Button";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import styles from "./AttendanceHistoryList.module.css";

export interface AttendanceHistoryListProps {
  defaultTermId?: string;
  sectionOptions?: FilterOption[];
  termOptions?: FilterOption[];
}

/** API enum labels in filter — distinct from AttendanceStatusCell badge copy for Playwright/DOM queries */
const STATUS_OPTIONS: FilterOption[] = [
  { value: "Present", label: "Present" },
  { value: "Late", label: "Late" },
  { value: "Absent", label: "Absent" },
  { value: "Manual Present", label: "Manual Present" },
  { value: "Excused", label: "Excused" },
];

export function AttendanceHistoryList({
  defaultTermId,
  sectionOptions = [],
  termOptions = [],
}: AttendanceHistoryListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => {
    const parsed = parseListingQuery(searchParams);
    if (!parsed.termId && defaultTermId) {
      return { ...parsed, termId: defaultTermId };
    }
    return parsed;
  }, [defaultTermId, searchParams]);

  const [rows, setRows] = useState<AttendanceHistoryRow[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const syncQuery = useCallback(
    (next: typeof query) => {
      setSearchParams(listingQueryToSearchParams(next), { replace: true });
    },
    [setSearchParams],
  );

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchAttendanceHistory(query);
    if (result.ok) {
      setRows(result.rows);
      setTotalItems(result.pagination.totalItems);
      setTotalPages(result.pagination.totalPages);
    } else {
      setRows([]);
      setTotalItems(0);
      setTotalPages(1);
      setError(result.message);
    }
    setLoading(false);
  }, [query]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const grouped = useMemo(() => groupRowsBySection(rows), [rows]);

  const columns = useMemo(
    () => [
      {
        id: "session",
        header: "Buổi học",
        cell: (row: AttendanceHistoryRow) => (
          <div>
            <strong>{row.sectionCode}</strong>
            <div className={styles.sessionMeta}>{formatCheckInTimestamp(row.sessionDate)}</div>
          </div>
        ),
      },
      {
        id: "status",
        header: "Trạng thái",
        cell: (row: AttendanceHistoryRow) => (
          <AttendanceStatusCell status={row.attendanceStatus} method={row.checkInMethod} />
        ),
      },
      {
        id: "checkInAt",
        header: "Thời gian",
        cell: (row: AttendanceHistoryRow) =>
          row.checkInAt ? formatCheckInTimestamp(row.checkInAt) : "—",
      },
    ],
    [],
  );

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);

  return (
    <div className={styles.list} data-testid="attendance-history-list">
      <TableToolbar
        termId={query.termId}
        termOptions={termOptions}
        classSectionId={query.classSectionId}
        sectionOptions={sectionOptions}
        status={query.status}
        statusOptions={STATUS_OPTIONS}
        sortOrder={query.sortOrder}
        onTermChange={(value) =>
          syncQuery({ ...query, termId: value || undefined, page: 1 })
        }
        onSectionChange={(value) =>
          syncQuery({ ...query, classSectionId: value || undefined, page: 1 })
        }
        onStatusChange={(value) =>
          syncQuery({ ...query, status: value || undefined, page: 1 })
        }
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "desc" ? "asc" : "desc",
            page: 1,
          })
        }
        onClearFilters={() => syncQuery({ ...DEFAULT_LISTING_QUERY, termId: defaultTermId })}
      />

      {loading ? <div className={styles.skeleton} aria-busy="true" /> : null}

      {!loading && error ? (
        <FeedbackAlert variant="danger" title="Không thể tải lịch sử">
          {error}
          <div className={styles.retryRow}>
            <Button variant="secondary" size="sm" onClick={() => void loadHistory()}>
              Thử lại
            </Button>
          </div>
        </FeedbackAlert>
      ) : null}

      {!loading && !error && rows.length === 0 ? (
        <FeedbackAlert variant="info" title="Chưa có bản ghi điểm danh">
          Bạn chưa có bản ghi điểm danh trong phạm vi lọc hiện tại.
        </FeedbackAlert>
      ) : null}

      {!loading && !error && rows.length > 0 ? (
        <>
          {[...grouped.entries()].map(([sectionCode, sectionRows]) => (
            <section key={sectionCode} className={styles.sectionGroup}>
              <h2 className={styles.sectionHeading}>{sectionCode}</h2>
              <DataTable
                columns={columns}
                rows={sectionRows}
                rowKey={(row) => row.attendanceRecordId}
                caption={`Lịch sử điểm danh — ${sectionCode}`}
              />
            </section>
          ))}

          <div className={styles.pagination}>
            <p className={styles.paginationMeta}>
              Hiển thị {pageStart}–{pageEnd} / {totalItems} bản ghi
            </p>
            <div className={styles.paginationActions}>
              <Button
                variant="secondary"
                size="sm"
                disabled={query.page <= 1}
                onClick={() => syncQuery({ ...query, page: query.page - 1 })}
              >
                Trang trước
              </Button>
              <span className={styles.pageIndicator}>
                Trang {query.page} / {Math.max(totalPages, 1)}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={query.page >= totalPages}
                onClick={() => syncQuery({ ...query, page: query.page + 1 })}
              >
                Trang sau
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </div>
  );
}
