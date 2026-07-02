import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createAttendanceExport,
  downloadAttendanceExport,
  fetchAttendanceReport,
  type AttendanceReportRow,
  type ExportJobSummary,
} from "../../lib/api/reporting-api";
import {
  DEFAULT_LISTING_QUERY,
  listingQueryToSearchParams,
  parseListingQuery,
  type ListingQueryState,
} from "../../lib/listing/query-state";
import { formatCheckInTimestamp } from "../../lib/check-in/format-timestamp";
import { Button } from "../ui/Button";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import { AttendanceStatusCell } from "./AttendanceStatusCell";
import { ExportScopeSummary } from "./ExportScopeSummary";
import styles from "./AttendanceReportList.module.css";

export interface AttendanceReportListProps {
  roles: string[];
  defaultTermId?: string;
  termOptions?: FilterOption[];
  sectionOptions?: FilterOption[];
  canExport?: boolean;
  readOnlyStaff?: boolean;
  /** When true, render listing chrome only while auth/scope resolves (no table fetch). */
  authPending?: boolean;
}

const STATUS_OPTIONS: FilterOption[] = [
  { value: "Present", label: "Present" },
  { value: "Late", label: "Late" },
  { value: "Absent", label: "Absent" },
  { value: "Manual Present", label: "Manual Present" },
  { value: "Excused", label: "Excused" },
];

const SORT_OPTIONS: FilterOption[] = [
  { value: "date", label: "Ngày học" },
  { value: "status", label: "Trạng thái" },
  { value: "classSectionId", label: "Lớp học phần" },
];

type ExportPanelState =
  | { stage: "idle" }
  | { stage: "confirming" }
  | { stage: "exporting" }
  | { stage: "completed"; job: ExportJobSummary; filename: string; csv: string }
  | { stage: "error"; message: string; code: string };

function hasResultFilters(query: ListingQueryState): boolean {
  return Boolean(query.search || query.status || query.from || query.to);
}

function createCsvDownload(csv: string, filename: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** Traceability: FR-27 FR-28 BR-18 AC-15 AC-16 AC-17 */
export function AttendanceReportList({
  roles,
  defaultTermId,
  termOptions = [],
  sectionOptions = [],
  canExport = false,
  readOnlyStaff = false,
  authPending = false,
}: AttendanceReportListProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => {
    const parsed = parseListingQuery(searchParams);
    return {
      ...parsed,
      termId: parsed.termId ?? defaultTermId,
      sortBy: SORT_OPTIONS.some((option) => option.value === parsed.sortBy) ? parsed.sortBy : "date",
    };
  }, [defaultTermId, searchParams]);

  const [rows, setRows] = useState<AttendanceReportRow[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");
  const [exportPanel, setExportPanel] = useState<ExportPanelState>({ stage: "idle" });

  const syncQuery = useCallback(
    (next: ListingQueryState) => {
      setSearchParams(listingQueryToSearchParams(next), { replace: true });
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

  const loadReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchAttendanceReport(query);
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
    if (authPending) {
      return;
    }
    void loadReport();
  }, [authPending, loadReport]);

  const columns = useMemo(
    () => [
      {
        id: "student",
        header: "Sinh viên",
        cell: (row: AttendanceReportRow) => (
          <div>
            <strong>{row.studentCode}</strong>
            <div className={styles.meta}>{row.studentUserId.slice(0, 8)}</div>
          </div>
        ),
      },
      {
        id: "section",
        header: "Lớp học phần",
        cell: (row: AttendanceReportRow) => (
          <div>
            <strong>{row.sectionCode}</strong>
            <div className={styles.meta}>{row.classSectionId.slice(0, 8)}</div>
          </div>
        ),
      },
      {
        id: "sessionDate",
        header: "Ngày học",
        cell: (row: AttendanceReportRow) => formatCheckInTimestamp(row.sessionDate),
      },
      {
        id: "status",
        header: "Trạng thái",
        cell: (row: AttendanceReportRow) => (
          <AttendanceStatusCell
            status={row.attendanceStatus}
            method={row.checkInMethod}
            compact
          />
        ),
      },
      {
        id: "checkInAt",
        header: "Thời gian điểm danh",
        cell: (row: AttendanceReportRow) =>
          row.checkInAt ? formatCheckInTimestamp(row.checkInAt) : "—",
      },
      ...(readOnlyStaff
        ? [
            {
              id: "evidence",
              header: "Bằng chứng",
              cell: (row: AttendanceReportRow) => (
                <div className={styles.evidenceLinks}>
                  <Link
                    className={styles.evidenceLink}
                    to={`/audit/sessions/${row.classSessionId}/roster`}
                  >
                    Danh sách buổi học
                  </Link>
                  <Link
                    className={styles.evidenceLink}
                    to={`/audit/logs?targetId=${encodeURIComponent(row.studentUserId)}`}
                  >
                    Audit
                  </Link>
                </div>
              ),
            },
          ]
        : []),
    ],
    [readOnlyStaff],
  );

  const pageStart = totalItems === 0 ? 0 : (query.page - 1) * query.pageSize + 1;
  const pageEnd = Math.min(query.page * query.pageSize, totalItems);

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
    if (query.classSectionId) {
      const label =
        sectionOptions.find((option) => option.value === query.classSectionId)?.label ??
        query.classSectionId.slice(0, 8);
      chips.push({
        id: "classSectionId",
        label: `Lớp học phần: ${label}`,
        onRemove: () => syncQuery({ ...query, classSectionId: undefined, page: 1 }),
      });
    }
    if (query.status) {
      chips.push({
        id: "status",
        label: `Trạng thái: ${query.status}`,
        onRemove: () => syncQuery({ ...query, status: undefined, page: 1 }),
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
  }, [query, sectionOptions, syncQuery]);

  const confirmExport = async () => {
    setExportPanel({ stage: "exporting" });
    const exportResult = await createAttendanceExport(query);
    if (!exportResult.ok) {
      setExportPanel({ stage: "error", code: exportResult.code, message: exportResult.message });
      return;
    }

    const downloadResult = await downloadAttendanceExport(exportResult.job.exportJobId);
    if (!downloadResult.ok) {
      setExportPanel({
        stage: "error",
        code: downloadResult.code,
        message: downloadResult.message,
      });
      return;
    }

    createCsvDownload(downloadResult.csv, downloadResult.filename);
    setExportPanel({
      stage: "completed",
      job: exportResult.job,
      csv: downloadResult.csv,
      filename: downloadResult.filename,
    });
  };

  return (
    <div className={styles.list} data-testid="attendance-report-list">
      <TableToolbar
        search={searchDraft}
        searchPlaceholder="Tìm MSSV hoặc tên sinh viên…"
        onSearchChange={setSearchDraft}
        termId={query.termId}
        termOptions={termOptions}
        classSectionId={query.classSectionId}
        sectionOptions={sectionOptions}
        status={query.status}
        statusOptions={STATUS_OPTIONS}
        from={query.from}
        to={query.to}
        onFromChange={(value) => syncQuery({ ...query, from: value || undefined, page: 1 })}
        onToChange={(value) => syncQuery({ ...query, to: value || undefined, page: 1 })}
        sortBy={query.sortBy}
        sortOptions={SORT_OPTIONS}
        sortOrder={query.sortOrder}
        onTermChange={(value) => syncQuery({ ...query, termId: value || undefined, page: 1 })}
        onSectionChange={(value) =>
          syncQuery({ ...query, classSectionId: value || undefined, page: 1 })
        }
        onStatusChange={(value) => syncQuery({ ...query, status: value || undefined, page: 1 })}
        onSortByChange={(value) => syncQuery({ ...query, sortBy: value || "date", page: 1 })}
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "desc" ? "asc" : "desc",
            page: 1,
          })
        }
        onClearFilters={() => {
          setSearchDraft("");
          syncQuery({ ...DEFAULT_LISTING_QUERY, termId: defaultTermId });
        }}
      >
        {canExport ? (
          <Button
            onClick={() => setExportPanel({ stage: "confirming" })}
            disabled={loading || Boolean(error)}
          >
            Xuất CSV
          </Button>
        ) : null}
      </TableToolbar>

      {activeFilterChips.length > 0 ? (
        <div className={styles.activeFilters} role="group" aria-label="Bộ lọc báo cáo đang áp dụng">
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

      {exportPanel.stage !== "idle" ? (
        <div className={styles.exportPanel}>
          {exportPanel.stage === "confirming" ? (
            <>
              <ExportScopeSummary
                roles={roles}
                query={query}
                termOptions={termOptions}
                sectionOptions={sectionOptions}
                totalItems={totalItems}
              />
              <div className={styles.exportActions}>
                <Button onClick={() => void confirmExport()}>Xác nhận xuất CSV</Button>
                <Button variant="secondary" onClick={() => setExportPanel({ stage: "idle" })}>
                  Hủy
                </Button>
              </div>
            </>
          ) : null}

          {exportPanel.stage === "exporting" ? (
            <FeedbackAlert variant="brand" title="Đang tạo CSV">
              Backend đang tạo file trong phạm vi đã xác nhận. Tác vụ này sẽ ghi audit khi hoàn tất.
            </FeedbackAlert>
          ) : null}

          {exportPanel.stage === "completed" ? (
            <FeedbackAlert variant="success" title="Xuất CSV thành công">
              Job {exportPanel.job.exportJobId.slice(0, 8)} đã hoàn tất với định dạng{" "}
              {exportPanel.job.format}. File {exportPanel.filename} đã được tải xuống và audit đã
              được ghi cho hành động xuất.
              <div className={styles.exportActions}>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => createCsvDownload(exportPanel.csv, exportPanel.filename)}
                >
                  Tải lại CSV
                </Button>
              </div>
            </FeedbackAlert>
          ) : null}

          {exportPanel.stage === "error" ? (
            <FeedbackAlert variant="danger" title={`Không thể xuất (${exportPanel.code})`}>
              {exportPanel.message}
            </FeedbackAlert>
          ) : null}
        </div>
      ) : null}

      {authPending ? (
        <div className={styles.skeleton} aria-busy="true" />
      ) : (
        <>
          {loading ? <div className={styles.skeleton} aria-busy="true" /> : null}

          {!loading && error ? (
            <FeedbackAlert variant="danger" title="Không thể tải báo cáo">
              {error}
              <div className={styles.retryRow}>
                <Button variant="secondary" size="sm" onClick={() => void loadReport()}>
                  Thử lại
                </Button>
              </div>
            </FeedbackAlert>
          ) : null}

          {!loading && !error && rows.length === 0 ? (
            <FeedbackAlert
              variant={hasResultFilters(query) ? "warning" : "info"}
              title={hasResultFilters(query) ? "Không tìm thấy kết quả" : "Chưa có dữ liệu báo cáo"}
            >
              {hasResultFilters(query)
                ? "Không có bản ghi nào khớp với bộ lọc hiện tại trong phạm vi được cấp."
                : "Chưa có bản ghi điểm danh trong phạm vi báo cáo này."}
              {hasResultFilters(query) ? (
                <div className={styles.retryRow}>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      setSearchDraft("");
                      syncQuery({ ...DEFAULT_LISTING_QUERY, termId: defaultTermId });
                    }}
                  >
                    Xóa bộ lọc
                  </Button>
                </div>
              ) : null}
            </FeedbackAlert>
          ) : null}

          {!loading && !error && rows.length > 0 ? (
            <>
              <DataTable
                columns={columns}
                rows={rows}
                rowKey={(row) => row.attendanceRecordId}
                caption="Báo cáo điểm danh PG-13"
              />
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
        </>
      )}
    </div>
  );
}
