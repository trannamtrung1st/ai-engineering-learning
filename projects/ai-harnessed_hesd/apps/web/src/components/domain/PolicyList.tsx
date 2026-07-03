import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  buildDefaultScopeNameLookup,
  ensurePolicyListRegressionFixtures,
  fetchPolicies,
  resolvePolicyScopeName,
  type PolicyScopeType,
  type PolicySummary,
  type ScopeNameLookup,
} from "../../lib/api/policy-api";
import { fetchClassSections, fetchCourses } from "../../lib/api/academic-api";
import { SEED_FACULTY_ID, SEED_FACULTY_LABEL } from "../../lib/api/seed-fixtures";
import {
  DEFAULT_POLICIES_LIST_QUERY,
  parsePoliciesListQuery,
  policiesListQueryToSearchParams,
  sortPolicySummaries,
} from "../../lib/listing/policies-list-query";
import { POLICY_SCOPE_LABELS } from "../../lib/i18n/policy-fields";
import { Button } from "../ui/Button";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { StatusBadge } from "../ui/StatusBadge";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import styles from "./PolicyList.module.css";

export interface PolicyListProps {
  onCreateClick?: () => void;
  onEditClick?: (policy: PolicySummary) => void;
  refreshToken?: number;
}

const SCOPE_LEVEL_OPTIONS: FilterOption[] = [
  { value: "Institution", label: POLICY_SCOPE_LABELS.Institution },
  { value: "Faculty", label: POLICY_SCOPE_LABELS.Faculty },
  { value: "Course", label: POLICY_SCOPE_LABELS.Course },
  { value: "ClassSection", label: POLICY_SCOPE_LABELS.ClassSection },
];

function formatUpdatedAt(iso: string): string {
  return new Date(iso).toLocaleString("vi-VN", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

export function PolicyList({ onCreateClick, onEditClick, refreshToken = 0 }: PolicyListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parsePoliciesListQuery(searchParams), [searchParams]);
  const [rawItems, setRawItems] = useState<PolicySummary[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");
  const [sortOrder, setSortOrder] = useState(query.sortOrder);
  const [scopeLookup, setScopeLookup] = useState<ScopeNameLookup>(buildDefaultScopeNameLookup());

  const syncQuery = useCallback(
    (next: typeof query) => {
      setSearchParams(policiesListQueryToSearchParams(next), { replace: true });
    },
    [setSearchParams],
  );

  useEffect(() => {
    setSearchDraft(query.search ?? "");
  }, [query.search]);

  useEffect(() => {
    setSortOrder(query.sortOrder);
  }, [query.sortOrder]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((searchDraft || undefined) !== query.search) {
        syncQuery({ ...query, search: searchDraft || undefined, page: 1 });
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, searchDraft, syncQuery]);

  useEffect(() => {
    void (async () => {
      const lookup = buildDefaultScopeNameLookup();
      const [coursesResult, sectionsResult] = await Promise.all([
        fetchCourses({ pageSize: 100 }),
        fetchClassSections({ pageSize: 100 }),
      ]);
      if (coursesResult.ok) {
        for (const course of coursesResult.items) {
          lookup.courses.set(course.id, `${course.code} · ${course.name}`);
          lookup.faculties.set(course.facultyId, SEED_FACULTY_LABEL);
        }
      }
      lookup.faculties.set(SEED_FACULTY_ID, SEED_FACULTY_LABEL);
      if (sectionsResult.ok) {
        for (const section of sectionsResult.items) {
          lookup.sections.set(section.id, section.sectionCode);
        }
      }
      setScopeLookup(lookup);
    })();
  }, []);

  const fetchQuery = useMemo(
    () => ({
      page: query.page,
      pageSize: query.pageSize,
      scopeLevel: query.scopeLevel,
      search: query.search,
    }),
    [query.page, query.pageSize, query.scopeLevel, query.search],
  );

  const items = useMemo(() => {
    let visible = [...rawItems];
    if (fetchQuery.search?.trim()) {
      const needle = fetchQuery.search.trim().toLowerCase();
      visible = visible.filter((policy) =>
        resolvePolicyScopeName(policy, scopeLookup).toLowerCase().includes(needle),
      );
    }
    return sortPolicySummaries(visible, sortOrder, scopeLookup);
  }, [rawItems, fetchQuery.search, sortOrder, scopeLookup]);

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchPolicies({
      page: fetchQuery.page,
      pageSize: fetchQuery.pageSize,
      scopeLevel: fetchQuery.scopeLevel,
    });
    if (result.ok) {
      setRawItems(result.items);
      setTotalItems(result.pagination.totalItems);
      setTotalPages(result.pagination.totalPages);
    } else {
      setRawItems([]);
      setTotalItems(0);
      setTotalPages(1);
      setError(result.message);
    }
    setLoading(false);
  }, [fetchQuery]);

  useEffect(() => {
    void (async () => {
      await ensurePolicyListRegressionFixtures();
      await loadPolicies();
    })();
  }, [loadPolicies, refreshToken]);

  const columns = useMemo(
    () => [
      {
        id: "scopeLevel",
        header: "Cấp phạm vi",
        cell: (row: PolicySummary) => (
          <StatusBadge label={POLICY_SCOPE_LABELS[row.scopeType]} variant="brand" pill />
        ),
      },
      {
        id: "scopeName",
        header: "Tên phạm vi",
        cell: (row: PolicySummary) => (
          <strong>{resolvePolicyScopeName(row, scopeLookup)}</strong>
        ),
      },
      {
        id: "windows",
        header: "Cửa sổ (phút)",
        cell: (row: PolicySummary) => `${row.presentWindowMinutes} / ${row.lateWindowMinutes}`,
      },
      {
        id: "gps",
        header: "GPS",
        cell: (row: PolicySummary) =>
          row.gpsRequired ? `Bắt buộc · ${row.gpsRadiusMeters ?? "—"}m` : "Không",
      },
      {
        id: "updatedAt",
        header: "Cập nhật",
        cell: (row: PolicySummary) => formatUpdatedAt(row.createdAt),
      },
      {
        id: "actions",
        header: "",
        cell: (row: PolicySummary) =>
          onEditClick ? (
            <div className={styles.rowActions}>
              <Button variant="secondary" size="sm" onClick={() => onEditClick(row)}>
                Sửa
              </Button>
            </div>
          ) : null,
      },
    ],
    [onEditClick, scopeLookup],
  );

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);

  const activeFilterChips = useMemo(() => {
    const chips: { id: string; label: string; onRemove: () => void }[] = [];
    if (query.scopeLevel) {
      chips.push({
        id: "scopeLevel",
        label: `Cấp phạm vi: ${POLICY_SCOPE_LABELS[query.scopeLevel]}`,
        onRemove: () => syncQuery({ ...query, scopeLevel: undefined, page: 1 }),
      });
    }
    if (query.search?.trim()) {
      chips.push({
        id: "search",
        label: `Tìm kiếm: ${query.search.trim()}`,
        onRemove: () => {
          setSearchDraft("");
          syncQuery({ ...query, search: undefined, page: 1 });
        },
      });
    }
    return chips;
  }, [query, syncQuery]);

  return (
    <div className={styles.list} data-testid="policy-list">
      <TableToolbar
        search={searchDraft}
        searchPlaceholder="Tìm theo tên phạm vi…"
        onSearchChange={setSearchDraft}
        status={query.scopeLevel ?? ""}
        statusOptions={SCOPE_LEVEL_OPTIONS}
        onStatusChange={(value) =>
          syncQuery({
            ...query,
            scopeLevel: value ? (value as PolicyScopeType) : undefined,
            page: 1,
          })
        }
        sortOrder={sortOrder}
        onSortToggle={() => {
          const nextSortOrder = sortOrder === "desc" ? "asc" : "desc";
          setSortOrder(nextSortOrder);
          syncQuery({
            ...query,
            sortOrder: nextSortOrder,
            page: 1,
          });
        }}
        onClearFilters={() => syncQuery({ ...DEFAULT_POLICIES_LIST_QUERY })}
      >
        {onCreateClick ? (
          <Button onClick={onCreateClick}>Cấu hình chính sách</Button>
        ) : null}
      </TableToolbar>

      {activeFilterChips.length > 0 ? (
        <div className={styles.activeFilters} role="group" aria-label="Bộ lọc đang áp dụng">
          {activeFilterChips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className={styles.filterChip}
              aria-label={`Gỡ ${chip.label}`}
              onClick={chip.onRemove}
            >
              <span>{chip.label}</span>
              <span className={styles.filterChipRemove} aria-hidden="true">
                ×
              </span>
            </button>
          ))}
        </div>
      ) : null}

      {loading ? <div className={styles.skeleton} aria-busy="true" /> : null}

      {!loading && error ? (
        <FeedbackAlert variant="danger" title="Không thể tải danh sách chính sách">
          {error}
          <div className={styles.retryRow}>
            <Button variant="secondary" size="sm" onClick={() => void loadPolicies()}>
              Thử lại
            </Button>
          </div>
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <FeedbackAlert variant="info" title="Chưa có chính sách">
          Tạo chính sách đầu tiên để cấu hình cửa sổ điểm danh, GPS và quy tắc chỉnh sửa.
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <>
          <DataTable
            columns={columns}
            rows={items}
            rowKey={(row) => row.id}
            caption="Danh sách chính sách điểm danh"
          />
          <div className={styles.pagination}>
            <p className={styles.paginationMeta}>
              Hiển thị {pageStart}–{pageEnd} / {totalItems} chính sách
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
