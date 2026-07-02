import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  fetchTerms,
  formatTermDates,
  type TermSummary,
} from "../../lib/api/academic-api";
import {
  DEFAULT_TERMS_LIST_QUERY,
  parseTermsListQuery,
  termsListQueryToSearchParams,
} from "../../lib/listing/terms-list-query";
import { Button } from "../ui/Button";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { StatusBadge } from "../ui/StatusBadge";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import styles from "./TermList.module.css";

export interface TermListProps {
  onCreateClick?: () => void;
  refreshToken?: number;
}

const ACTIVE_OPTIONS: FilterOption[] = [
  { value: "true", label: "Active" },
  { value: "false", label: "Inactive" },
];

export function TermList({ onCreateClick, refreshToken = 0 }: TermListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parseTermsListQuery(searchParams), [searchParams]);
  const [items, setItems] = useState<TermSummary[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");

  const syncQuery = useCallback(
    (next: typeof query) => {
      setSearchParams(termsListQueryToSearchParams(next), { replace: true });
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

  const loadTerms = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchTerms({
      page: query.page,
      pageSize: query.pageSize,
      activeOnly: query.activeOnly,
      search: query.search,
    });
    if (result.ok) {
      let sorted = [...result.items];
      if (query.activeOnly === false) {
        sorted = sorted.filter((term) => !term.isActive);
      }
      sorted.sort((a, b) => {
        const cmp = a.code.localeCompare(b.code);
        return query.sortOrder === "desc" ? -cmp : cmp;
      });
      setItems(sorted);
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
    void loadTerms();
  }, [loadTerms, refreshToken]);

  const columns = useMemo(
    () => [
      {
        id: "code",
        header: "Mã học kỳ",
        cell: (row: TermSummary) => <strong>{row.code}</strong>,
      },
      {
        id: "name",
        header: "Tên học kỳ",
        cell: (row: TermSummary) => row.name,
      },
      {
        id: "dates",
        header: "Thời gian",
        cell: (row: TermSummary) => formatTermDates(row.startDate, row.endDate),
      },
      {
        id: "active",
        header: "Trạng thái",
        cell: (row: TermSummary) => (
          <StatusBadge
            label={row.isActive ? "Đang hoạt động" : "Ngừng hoạt động"}
            variant={row.isActive ? "success" : "gray"}
            pill
          />
        ),
      },
    ],
    [],
  );

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);
  const activeFilter = query.activeOnly === true ? "true" : query.activeOnly === false ? "false" : "";

  return (
    <div className={styles.list} data-testid="term-list">
      <TableToolbar
        search={searchDraft}
        searchPlaceholder="Tìm mã hoặc tên học kỳ…"
        onSearchChange={setSearchDraft}
        status={activeFilter}
        statusOptions={ACTIVE_OPTIONS}
        onStatusChange={(value) =>
          syncQuery({
            ...query,
            activeOnly: value === "true" ? true : value === "false" ? false : undefined,
            page: 1,
          })
        }
        sortOrder={query.sortOrder}
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "desc" ? "asc" : "desc",
            page: 1,
          })
        }
        onClearFilters={() => syncQuery({ ...DEFAULT_TERMS_LIST_QUERY })}
      >
        {onCreateClick ? (
          <Button onClick={onCreateClick}>Tạo học kỳ</Button>
        ) : null}
      </TableToolbar>

      {loading ? <div className={styles.skeleton} aria-busy="true" /> : null}

      {!loading && error ? (
        <FeedbackAlert variant="danger" title="Không thể tải danh sách học kỳ">
          {error}
          <div className={styles.retryRow}>
            <Button variant="secondary" size="sm" onClick={() => void loadTerms()}>
              Thử lại
            </Button>
          </div>
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <FeedbackAlert variant="info" title="Chưa có học kỳ">
          Tạo học kỳ đầu tiên để bắt đầu thiết lập cấu trúc học thuật.
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <>
          <DataTable columns={columns} rows={items} rowKey={(row) => row.id} caption="Danh sách học kỳ" />
          <div className={styles.pagination}>
            <p className={styles.paginationMeta}>
              Hiển thị {pageStart}–{pageEnd} / {totalItems} học kỳ
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
