import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  fetchSessionRoster,
  subscribeSessionRosterEvents,
  type RosterRow,
  type SessionRoster,
} from "../../lib/api/roster-api";
import { formatCheckInTimestamp } from "../../lib/check-in/format-timestamp";
import {
  DEFAULT_ROSTER_LIST_QUERY,
  filterAndSortRosterRows,
  parseRosterListQuery,
  rosterListQueryToSearchParams,
} from "../../lib/listing/roster-list-query";
import { AttemptOutcomeCell } from "./AttemptOutcomeCell";
import { AttendanceStatusCell } from "./AttendanceStatusCell";
import { ManualCorrectionDialog } from "./ManualCorrectionDialog";
import { Button } from "../ui/Button";
import { DataTable } from "../ui/DataTable";
import { FeedbackAlert } from "../ui/FeedbackAlert";
import { SessionStatusBadge, type SessionState } from "../ui/StatusBadge";
import { TableToolbar, type FilterOption } from "../ui/TableToolbar";
import styles from "./LiveRosterPanel.module.css";

/** API enum labels — distinct from AttendanceStatusCell badge copy */
const STATUS_FILTER_OPTIONS: FilterOption[] = [
  { value: "Present", label: "Present" },
  { value: "Late", label: "Late" },
  { value: "Pending", label: "Pending" },
  { value: "Absent", label: "Absent" },
  { value: "Manual Present", label: "Manual Present" },
  { value: "Excused", label: "Excused" },
];

const ATTEMPT_OUTCOME_OPTIONS: FilterOption[] = [
  { value: "ExpiredQr", label: "ExpiredQr" },
  { value: "DuplicateCheckIn", label: "DuplicateCheckIn" },
  { value: "GpsDisabled", label: "GpsDisabled" },
  { value: "OutOfRadius", label: "OutOfRadius" },
  { value: "LowAccuracy", label: "LowAccuracy" },
  { value: "NotEnrolled", label: "NotEnrolled" },
];

export interface LiveRosterPanelProps {
  sessionId: string;
  sectionCode?: string;
}

export function LiveRosterPanel({ sessionId, sectionCode }: LiveRosterPanelProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parseRosterListQuery(searchParams), [searchParams]);
  const [roster, setRoster] = useState<SessionRoster | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState(query.search ?? "");
  const [correctionRow, setCorrectionRow] = useState<RosterRow | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);

  const syncQuery = useCallback(
    (next: typeof query) => {
      setSearchParams(rosterListQueryToSearchParams(next), { replace: true });
    },
    [setSearchParams],
  );

  const loadRoster = useCallback(async () => {
    setLoading(true);
    setError(null);
    const result = await fetchSessionRoster(sessionId);
    if (result.ok) {
      setRoster(result.roster);
    } else {
      setRoster(null);
      setError(result.message);
    }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => {
    void loadRoster();
  }, [loadRoster]);

  useEffect(() => {
    setSearchDraft(query.search ?? "");
  }, [query.search]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((searchDraft || undefined) !== query.search) {
        syncQuery({ ...query, search: searchDraft || undefined });
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [query, searchDraft, syncQuery]);

  useEffect(() => {
    if (!roster || roster.state !== "Open") {
      setLiveConnected(false);
      return;
    }

    const unsubscribe = subscribeSessionRosterEvents(sessionId, {
      onSnapshot: (next) => {
        setRoster(next);
        setLiveConnected(true);
      },
      onUpdate: (next) => {
        setRoster(next);
        setLiveConnected(true);
      },
      onDisconnect: () => setLiveConnected(false),
    });

    return unsubscribe;
  }, [roster?.state, sessionId]);

  const filteredRows = useMemo(() => {
    if (!roster) return [];
    return filterAndSortRosterRows(roster.rows, query);
  }, [query, roster]);

  if (loading) {
    return <div className={styles.panel} aria-busy="true" data-testid="live-roster-loading" />;
  }

  if (error || !roster) {
    return (
      <FeedbackAlert variant="danger" title="Không thể tải danh sách">
        {error ?? "Danh sách điểm danh không khả dụng."}
      </FeedbackAlert>
    );
  }

  return (
    <div className={styles.panel} data-testid="live-roster-panel">
      <div className={styles.summary} aria-label="Tóm tắt điểm danh">
        <div className={[styles.chip, styles.chipPresent].join(" ")}>
          <span className={styles.chipLabel}>Có mặt</span>
          <span className={styles.chipValue}>{roster.counts.present}</span>
        </div>
        <div className={[styles.chip, styles.chipLate].join(" ")}>
          <span className={styles.chipLabel}>Muộn</span>
          <span className={styles.chipValue}>{roster.counts.late}</span>
        </div>
        <div className={[styles.chip, styles.chipPending].join(" ")}>
          <span className={styles.chipLabel}>Chưa điểm danh</span>
          <span className={styles.chipValue}>{roster.counts.pending}</span>
        </div>
        <div className={[styles.chip, styles.chipRejected].join(" ")}>
          <span className={styles.chipLabel}>Lần thử lỗi</span>
          <span className={styles.chipValue}>{roster.counts.rejectedAttempts}</span>
        </div>
      </div>

      <div className={styles.summary}>
        <SessionStatusBadge state={roster.state as SessionState} />
        {sectionCode ? <span>{sectionCode}</span> : null}
        {roster.state === "Open" && liveConnected ? (
          <div className={styles.liveBanner} role="status">
            <span className={styles.liveDot} aria-hidden="true" />
            Cập nhật theo thời gian thực
          </div>
        ) : null}
      </div>

      <TableToolbar
        search={searchDraft}
        searchPlaceholder="Tìm mã hoặc tên sinh viên…"
        onSearchChange={setSearchDraft}
        status={query.status}
        statusOptions={STATUS_FILTER_OPTIONS}
        onStatusChange={(value) => syncQuery({ ...query, status: value || undefined })}
        sortOrder={query.sortOrder}
        onSortToggle={() =>
          syncQuery({
            ...query,
            sortOrder: query.sortOrder === "asc" ? "desc" : "asc",
          })
        }
        onClearFilters={() => {
          setSearchDraft("");
          syncQuery(DEFAULT_ROSTER_LIST_QUERY);
        }}
      >
        <label className={styles.field}>
          <span className={styles.chipLabel}>Lần thử</span>
          <select
            aria-label="Lọc theo kết quả lần thử"
            value={query.attemptOutcome ?? ""}
            onChange={(event) =>
              syncQuery({ ...query, attemptOutcome: event.target.value || undefined })
            }
          >
            <option value="">Tất cả lần thử</option>
            {ATTEMPT_OUTCOME_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </TableToolbar>

      <DataTable
        caption="Danh sách sinh viên điểm danh"
        emptyMessage="Chưa có sinh viên điểm danh phù hợp bộ lọc."
        rows={filteredRows}
        rowKey={(row) => row.studentUserId}
        columns={[
          {
            id: "identity",
            header: "Sinh viên",
            cell: (row) => (
              <div className={styles.identity}>
                <span className={styles.code}>{row.studentCode}</span>
                <span className={styles.name}>{row.displayName}</span>
              </div>
            ),
          },
          {
            id: "status",
            header: "Trạng thái",
            cell: (row) => (
              <AttendanceStatusCell status={row.attendanceStatus} method={row.checkInMethod} />
            ),
          },
          {
            id: "attempt",
            header: "Lần thử gần nhất",
            cell: (row) => <AttemptOutcomeCell outcome={row.latestAttemptOutcome} />,
          },
          {
            id: "time",
            header: "Thời gian",
            cell: (row) => (
              <span className={styles.time}>
                {row.checkInAt ? formatCheckInTimestamp(row.checkInAt) : "—"}
              </span>
            ),
          },
          {
            id: "action",
            header: "Thao tác",
            cell: (row) => (
              <div className={styles.actions}>
                <Button
                  size="sm"
                  variant="secondary"
                  type="button"
                  onClick={() => setCorrectionRow(row)}
                >
                  Điều chỉnh
                </Button>
              </div>
            ),
          },
        ]}
      />

      {correctionRow ? (
        <ManualCorrectionDialog
          sessionId={sessionId}
          row={correctionRow}
          open
          onClose={() => setCorrectionRow(null)}
          onSuccess={() => void loadRoster()}
        />
      ) : null}
    </div>
  );
}
