import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import {
  DEFAULT_SESSION_LIST_QUERY,
  parseSessionListQuery,
  sessionListQueryToSearchParams,
} from "../../lib/listing/session-list-query";
import {
  fetchClassSessions,
  formatRoomLabel,
  formatScheduledAt,
  formatSessionLabel,
  type ClassSessionSummary,
} from "../../lib/api/session-api";
import { Button } from "../ui/Button";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { SessionStatusBadge } from "../ui/StatusBadge";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import styles from "./LecturerSessionList.module.css";

/** API enum labels — distinct from SessionStatusBadge copy for filter queries */
const STATE_OPTIONS: FilterOption[] = [
  { value: "Scheduled", label: "Scheduled" },
  { value: "Open", label: "Open" },
  { value: "Closed", label: "Closed" },
  { value: "Cancelled", label: "Cancelled" },
];

export interface LecturerSessionListProps {
  sectionOptions?: FilterOption[];
}

export function LecturerSessionList({ sectionOptions = [] }: LecturerSessionListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parseSessionListQuery(searchParams), [searchParams]);
  const [items, setItems] = useState<ClassSessionSummary[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");

  const syncQuery = useCallback(
    (next: typeof query) => {
      setSearchParams(sessionListQueryToSearchParams(next), { replace: true });
    },
    [setSearchParams],
  );

  useEffect(() => {
    setSearchDraft(query.search ?? "");
  }, [query.search]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((searchDraft || undefined) !== query.search) {
        syncQuery({ ...query, search: searchDraft || undefined, page: 1 });
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, searchDraft, syncQuery]);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchClassSessions(query);
    if (result.ok) {
      setItems(result.items);
      setTotalItems(result.pagination.totalItems);
      setTotalPages(result.pagination.totalPages);
    } else {
      setItems([]);
      setTotalItems(0);
      setTotalPages(1);
      setError(result.message);
    }
    setLoading(false);
  }, [query]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  const columns = useMemo(
    () => [
      {
        id: "session",
        header: "Buổi học",
        cell: (row: ClassSessionSummary) => (
          <div>
            <strong>{row.sectionCode}</strong>
            <div className={styles.sessionMeta}>{formatSessionLabel(row)}</div>
          </div>
        ),
      },
      {
        id: "room",
        header: "Phòng",
        cell: (row: ClassSessionSummary) => formatRoomLabel(row),
      },
      {
        id: "start",
        header: "Giờ học",
        cell: (row: ClassSessionSummary) => formatScheduledAt(row.scheduledStartAt),
      },
      {
        id: "state",
        header: "Trạng thái",
        cell: (row: ClassSessionSummary) => <SessionStatusBadge state={row.state} />,
      },
      {
        id: "actions",
        header: "Thao tác",
        cell: (row: ClassSessionSummary) => (
          <div className={styles.rowActions}>
            <Link className={styles.linkAction} to={`/lecturer/sessions/${row.classSessionId}`}>
              Chi tiết
            </Link>
            {row.state === "Scheduled" ? (
              <Link
                className={styles.linkPrimary}
                to={`/lecturer/sessions/${row.classSessionId}?action=open`}
              >
                Mở điểm danh
              </Link>
            ) : null}
          </div>
        ),
      },
    ],
    [],
  );

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);

  return (
    <div className={styles.list} data-testid="lecturer-session-list">
      <TableToolbar
        classSectionId={query.classSectionId}
        sectionOptions={sectionOptions}
        status={query.state}
        statusOptions={STATE_OPTIONS}
        search={searchDraft}
        searchPlaceholder="Tìm mã lớp hoặc tên học phần…"
        onSearchChange={setSearchDraft}
        sortOrder={query.sortOrder}
        onSectionChange={(value) =>
          syncQuery({ ...query, classSectionId: value || undefined, page: 1 })
        }
        onStatusChange={(value) => syncQuery({ ...query, state: value || undefined, page: 1 })}
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "desc" ? "asc" : "desc",
            page: 1,
          })
        }
        onClearFilters={() => syncQuery({ ...DEFAULT_SESSION_LIST_QUERY })}
      />

      {loading ? <div className={styles.skeleton} aria-busy="true" /> : null}

      {!loading && error ? (
        <FeedbackAlert variant="danger" title="Không thể tải danh sách buổi học">
          {error}
          <div className={styles.retryRow}>
            <Button variant="secondary" size="sm" onClick={() => void loadSessions()}>
              Thử lại
            </Button>
          </div>
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <FeedbackAlert variant="info" title="Chưa có buổi học">
          Không có buổi học trong phạm vi lọc hiện tại.
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(row) => row.classSessionId}
            caption="Danh sách buổi học được phân công"
          />
          <div className={styles.pagination}>
            <p className={styles.paginationMeta}>
              Hiển thị {pageStart}–{pageEnd} / {totalItems} buổi học
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
