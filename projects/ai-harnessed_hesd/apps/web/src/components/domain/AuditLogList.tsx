import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchAuditLogs, type AuditLogEntry } from "../../lib/api/audit-api";
import {
  SEED_ACADEMIC_ADMIN_USER_ID,
  SEED_LECTURER_USER_ID,
} from "../../lib/api/seed-fixtures";
import {
  AUDIT_ACTION_TYPE_LABELS,
  AUDIT_TARGET_TYPE_LABELS,
  formatAuditActionType,
} from "../../lib/i18n/audit-action-types";
import {
  DEFAULT_AUDIT_LOGS_QUERY,
  auditLogsQueryToSearchParams,
  parseAuditLogsListQuery,
  type AuditLogsListQuery,
} from "../../lib/listing/audit-logs-list-query";
import { Button } from "../ui/Button";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import { AuditEntryRow } from "./AuditEntryRow";
import styles from "./AuditLogList.module.css";

const ACTION_TYPE_OPTIONS: FilterOption[] = Object.keys(AUDIT_ACTION_TYPE_LABELS).map((value) => ({
  value,
  label: formatAuditActionType(value),
}));

const TARGET_TYPE_OPTIONS: FilterOption[] = Object.keys(AUDIT_TARGET_TYPE_LABELS).map((value) => ({
  value,
  label: value,
}));

const ACTOR_OPTIONS: FilterOption[] = [
  { value: SEED_LECTURER_USER_ID, label: `${SEED_LECTURER_USER_ID.slice(0, 8)} (Lecturer)` },
  {
    value: SEED_ACADEMIC_ADMIN_USER_ID,
    label: `${SEED_ACADEMIC_ADMIN_USER_ID.slice(0, 8)} (AcademicAdmin)`,
  },
];

const SORT_OPTIONS: FilterOption[] = [{ value: "timestamp", label: "Thời điểm" }];

function hasResultFilters(query: AuditLogsListQuery): boolean {
  return Boolean(
    query.search ||
      query.actorUserId ||
      query.targetType ||
      query.targetId ||
      query.classSessionId ||
      query.actionType ||
      query.from ||
      query.to,
  );
}

function matchesSearch(entry: AuditLogEntry, needle: string): boolean {
  const haystack = [
    entry.actorDisplayName,
    entry.actorUserId,
    entry.targetId,
    entry.studentUserId,
    entry.targetType,
    formatAuditActionType(entry.actionType),
    entry.scopeFilterSummary,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(needle);
}

function sortEntries(items: AuditLogEntry[], sortOrder: "asc" | "desc"): AuditLogEntry[] {
  return [...items].sort((left, right) => {
    const delta = Date.parse(left.occurredAt) - Date.parse(right.occurredAt);
    return sortOrder === "asc" ? delta : -delta;
  });
}

export interface AuditLogListProps {
  readOnly?: boolean;
}

/** Traceability: FR-29 FR-30 FR-32 BR-22 AC-19 AC-16 */
export function AuditLogList({ readOnly = true }: AuditLogListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parseAuditLogsListQuery(searchParams), [searchParams]);
  const [rawItems, setRawItems] = useState<AuditLogEntry[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");

  const syncQuery = useCallback(
    (next: AuditLogsListQuery) => {
      setSearchParams(auditLogsQueryToSearchParams(next), { replace: true });
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

  const loadAuditLogs = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchAuditLogs(query);
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
  }, [query]);

  useEffect(() => {
    void loadAuditLogs();
  }, [loadAuditLogs]);

  const items = useMemo(() => {
    let visible = sortEntries(rawItems, query.sortOrder);
    if (query.search?.trim()) {
      const needle = query.search.trim().toLowerCase();
      visible = visible.filter((entry) => matchesSearch(entry, needle));
    }
    return visible;
  }, [query.search, query.sortOrder, rawItems]);

  const activeFilterChips = useMemo(() => {
    const chips: { id: string; label: string; onRemove: () => void }[] = [];
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
    if (query.actorUserId) {
      const label =
        ACTOR_OPTIONS.find((option) => option.value === query.actorUserId)?.label ??
        query.actorUserId.slice(0, 8);
      chips.push({
        id: "actorUserId",
        label: `Người thực hiện: ${label}`,
        onRemove: () => syncQuery({ ...query, actorUserId: undefined, page: 1 }),
      });
    }
    if (query.targetType) {
      chips.push({
        id: "targetType",
        label: `Loại đối tượng: ${query.targetType}`,
        onRemove: () => syncQuery({ ...query, targetType: undefined, page: 1 }),
      });
    }
    if (query.actionType) {
      chips.push({
        id: "actionType",
        label: `Hành động: ${formatAuditActionType(query.actionType)}`,
        onRemove: () => syncQuery({ ...query, actionType: undefined, page: 1 }),
      });
    }
    if (query.targetId) {
      chips.push({
        id: "targetId",
        label: `Đối tượng: ${query.targetId.slice(0, 8)}`,
        onRemove: () => syncQuery({ ...query, targetId: undefined, page: 1 }),
      });
    }
    if (query.from) {
      chips.push({
        id: "from",
        label: `Từ ngày: ${query.from}`,
        onRemove: () => syncQuery({ ...query, from: undefined, page: 1 }),
      });
    }
    if (query.to) {
      chips.push({
        id: "to",
        label: `Đến ngày: ${query.to}`,
        onRemove: () => syncQuery({ ...query, to: undefined, page: 1 }),
      });
    }
    return chips;
  }, [query, syncQuery]);

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);

  return (
    <div className={styles.list} data-testid="audit-log-list">
      <TableToolbar
        search={searchDraft}
        searchPlaceholder="Tìm người thực hiện hoặc đối tượng…"
        onSearchChange={setSearchDraft}
        from={query.from}
        to={query.to}
        onFromChange={(value) => syncQuery({ ...query, from: value || undefined, page: 1 })}
        onToChange={(value) => syncQuery({ ...query, to: value || undefined, page: 1 })}
        sortBy={query.sortBy}
        sortOptions={SORT_OPTIONS}
        sortOrder={query.sortOrder}
        onSortByChange={() => undefined}
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "desc" ? "asc" : "desc",
            page: 1,
          })
        }
        onClearFilters={() => {
          setSearchDraft("");
          syncQuery(DEFAULT_AUDIT_LOGS_QUERY);
        }}
        clearFiltersLabel="Đặt lại bộ lọc"
      >
        <div className={styles.extraFilters}>
          <label className={styles.filterField}>
            <span className={styles.filterLabel}>Người thực hiện</span>
            <select
              className={styles.filterSelect}
              aria-label="Lọc theo người thực hiện"
              value={query.actorUserId ?? ""}
              onChange={(event) =>
                syncQuery({ ...query, actorUserId: event.target.value || undefined, page: 1 })
              }
            >
              <option value="">Tất cả</option>
              {ACTOR_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.filterField}>
            <span className={styles.filterLabel}>Loại đối tượng</span>
            <select
              className={styles.filterSelect}
              aria-label="Lọc theo loại đối tượng"
              value={query.targetType ?? ""}
              onChange={(event) =>
                syncQuery({ ...query, targetType: event.target.value || undefined, page: 1 })
              }
            >
              <option value="">Tất cả</option>
              {TARGET_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className={styles.filterField}>
            <span className={styles.filterLabel}>Hành động</span>
            <select
              className={styles.filterSelect}
              aria-label="Lọc theo loại hành động"
              value={query.actionType ?? ""}
              onChange={(event) =>
                syncQuery({ ...query, actionType: event.target.value || undefined, page: 1 })
              }
            >
              <option value="">Tất cả</option>
              {ACTION_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </TableToolbar>

      {activeFilterChips.length > 0 ? (
        <div className={styles.activeFilters} role="group" aria-label="Bộ lọc audit đang áp dụng">
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
        <FeedbackAlert variant="danger" title="Không thể tải nhật ký audit">
          {error}
          <div className={styles.retryRow}>
            <Button variant="secondary" size="sm" onClick={() => void loadAuditLogs()}>
              Thử lại
            </Button>
          </div>
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length === 0 ? (
        <FeedbackAlert
          variant={hasResultFilters(query) ? "warning" : "info"}
          title={hasResultFilters(query) ? "Không tìm thấy kết quả" : "Chưa có bản ghi audit"}
        >
          {hasResultFilters(query)
            ? "Không có bản ghi audit nào khớp với bộ lọc hiện tại trong phạm vi được cấp."
            : "Chưa có sự kiện audit trong phạm vi tra cứu này."}
          {hasResultFilters(query) ? (
            <div className={styles.retryRow}>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => {
                  setSearchDraft("");
                  syncQuery(DEFAULT_AUDIT_LOGS_QUERY);
                }}
              >
                Đặt lại bộ lọc
              </Button>
            </div>
          ) : null}
        </FeedbackAlert>
      ) : null}

      {!loading && !error && items.length > 0 ? (
        <>
          <div className={styles.entryList}>
            {items.map((entry) => (
              <AuditEntryRow key={entry.id} entry={entry} readOnly={readOnly} />
            ))}
          </div>
          <div className={styles.pagination}>
            <p className={styles.paginationMeta}>
              Hiển thị {pageStart}–{pageEnd} / {totalItems} bản ghi trong phạm vi được cấp
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
