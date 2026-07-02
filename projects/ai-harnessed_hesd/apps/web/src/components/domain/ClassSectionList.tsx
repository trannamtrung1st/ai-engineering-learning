import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import { fetchClassSections, type ClassSectionSummary } from "../../lib/api/academic-api";
import {
  DEFAULT_CLASS_SECTIONS_LIST_QUERY,
  parseClassSectionsListQuery,
  classSectionsListQueryToSearchParams,
} from "../../lib/listing/class-sections-list-query";
import { Button } from "../ui/Button";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { StatusBadge } from "../ui/StatusBadge";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import styles from "./ClassSectionList.module.css";

export interface ClassSectionListProps {
  termOptions?: FilterOption[];
  onCreateClick?: () => void;
  refreshToken?: number;
}

export function ClassSectionList({
  termOptions = [],
  onCreateClick,
  refreshToken = 0,
}: ClassSectionListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parseClassSectionsListQuery(searchParams), [searchParams]);
  const [items, setItems] = useState<ClassSectionSummary[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");

  const syncQuery = useCallback(
    (next: typeof query) => {
      setSearchParams(classSectionsListQueryToSearchParams(next), { replace: true });
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

  const loadSections = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchClassSections({
      page: query.page,
      pageSize: query.pageSize,
      termId: query.termId,
      search: query.search,
    });
    if (result.ok) {
      const sorted = [...result.items].sort((a, b) => {
        const cmp = a.sectionCode.localeCompare(b.sectionCode);
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
    void loadSections();
  }, [loadSections, refreshToken]);

  const columns = useMemo(
    () => [
      {
        id: "code",
        header: "Mã lớp",
        cell: (row: ClassSectionSummary) => <strong>{row.sectionCode}</strong>,
      },
      {
        id: "term",
        header: "Học kỳ",
        cell: (row: ClassSectionSummary) => {
          const label = termOptions.find((opt) => opt.value === row.termId)?.label;
          return label ?? row.termId.slice(0, 8);
        },
      },
      {
        id: "active",
        header: "Trạng thái",
        cell: (row: ClassSectionSummary) => (
          <StatusBadge
            label={row.isActive ? "Đang mở" : "Đã đóng"}
            variant={row.isActive ? "success" : "gray"}
            pill
          />
        ),
      },
      {
        id: "actions",
        header: "Thao tác",
        cell: (row: ClassSectionSummary) => (
          <Link className={styles.linkAction} to={`/admin/class-sections/${row.id}/enrollments`}>
            Nhập đăng ký
          </Link>
        ),
      },
    ],
    [termOptions],
  );

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);

  return (
    <div className={styles.list} data-testid="class-section-list">
      <TableToolbar
        termId={query.termId}
        termOptions={termOptions}
        search={searchDraft}
        searchPlaceholder="Tìm mã lớp học phần…"
        onSearchChange={setSearchDraft}
        onTermChange={(value) => syncQuery({ ...query, termId: value || undefined, page: 1 })}
        sortOrder={query.sortOrder}
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "desc" ? "asc" : "desc",
            page: 1,
          })
        }
        onClearFilters={() => syncQuery({ ...DEFAULT_CLASS_SECTIONS_LIST_QUERY })}
      >
        {onCreateClick ? (
          <Button onClick={onCreateClick}>Tạo lớp học phần</Button>
        ) : null}
      </TableToolbar>

      {loading ? <div className={styles.skeleton} aria-busy="true" /> : null}

      {!loading && error ? (
        <FeedbackAlert variant="danger" title="Không thể tải danh sách lớp học phần">
          {error}
          <div className={styles.retryRow}>
            <Button variant="secondary" size="sm" onClick={() => void loadSections()}>
              Thử lại
            </Button>
          </div>
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <FeedbackAlert variant="info" title="Chưa có lớp học phần">
          Tạo lớp học phần để gán giảng viên và lịch học.
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(row) => row.id}
            caption="Danh sách lớp học phần"
          />
          <div className={styles.pagination}>
            <p className={styles.paginationMeta}>
              Hiển thị {pageStart}–{pageEnd} / {totalItems} lớp
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
