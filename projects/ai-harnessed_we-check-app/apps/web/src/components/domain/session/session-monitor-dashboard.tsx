import { AttendanceStatus } from "@wecheck/domain";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { StatusBadge } from "@/components/ui/status-badge";
import { SpoofAlertBadge } from "@/components/domain/session/spoof-alert-badge";
import { useSessionMonitorPoll } from "@/hooks/use-session-monitor-poll";
import type { SessionMonitorRecord } from "@/lib/session-monitor-api";
import {
  filterMonitorRecords,
  formatMonitorTimestamp,
  formatPollTime,
  sortMonitorRecords,
  type MonitorSortColumn,
  type MonitorSortDirection,
  type MonitorStatusFilter,
} from "@/lib/session-monitor-roster";

export interface SessionMonitorDashboardProps {
  sessionId?: string;
  /** When false (e.g. session Closed), polling stops per ui-states §7.3 */
  pollingEnabled?: boolean;
  /** Fallback when API unavailable (storybook / offline) */
  showCodeSharingAlert?: boolean;
  showSpoofAlert?: boolean;
}

const statusFilterOptions: Array<{ value: MonitorStatusFilter; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: AttendanceStatus.Present, label: "Có mặt" },
  { value: AttendanceStatus.Absent, label: "Vắng" },
  { value: AttendanceStatus.Excused, label: "Có phép" },
  { value: AttendanceStatus.Pending, label: "Chờ" },
];

function sortStorageKey(sessionId: string): string {
  return `wecheck-monitor-sort:${sessionId}`;
}

function readStoredSort(sessionId: string): {
  column: MonitorSortColumn | null;
  direction: MonitorSortDirection;
} {
  try {
    const raw = sessionStorage.getItem(sortStorageKey(sessionId));
    if (!raw) return { column: null, direction: "asc" };
    const parsed = JSON.parse(raw) as {
      column?: MonitorSortColumn | null;
      direction?: MonitorSortDirection;
    };
    return {
      column: parsed.column ?? null,
      direction: parsed.direction ?? "asc",
    };
  } catch {
    return { column: null, direction: "asc" };
  }
}

function writeStoredSort(
  sessionId: string,
  column: MonitorSortColumn | null,
  direction: MonitorSortDirection,
): void {
  sessionStorage.setItem(
    sortStorageKey(sessionId),
    JSON.stringify({ column, direction }),
  );
}

/** FR-15 / AC-15 / NFR-08 — live attendance monitor with security alerts */
export function SessionMonitorDashboard({
  sessionId,
  pollingEnabled = true,
  showCodeSharingAlert = false,
  showSpoofAlert = false,
}: SessionMonitorDashboardProps) {
  const monitorQuery = useSessionMonitorPoll(sessionId, pollingEnabled);
  const data = monitorQuery.data;

  const [statusFilter, setStatusFilter] = useState<MonitorStatusFilter>("all");
  const [sortColumn, setSortColumn] = useState<MonitorSortColumn | null>(null);
  const [sortDirection, setSortDirection] = useState<MonitorSortDirection>("asc");

  useEffect(() => {
    if (!sessionId) return;
    const stored = readStoredSort(sessionId);
    setSortColumn(stored.column);
    setSortDirection(stored.direction);
  }, [sessionId]);

  useEffect(() => {
    if (!monitorQuery.isError) return;
    toast.error("Không thể cập nhật dữ liệu điểm danh", { id: "monitor-poll-error" });
  }, [monitorQuery.isError]);

  const summary = data?.summary ?? {
    present: showSpoofAlert ? 1 : 1,
    pending: 2,
    absent: 0,
    enrolled: 3,
    excused: 0,
    rejected: 0,
  };

  const codeSharingAlert = data?.alerts?.codeSharing ?? showCodeSharingAlert;
  const sourceRecords: SessionMonitorRecord[] =
    data?.records ??
    (showSpoofAlert
      ? [
          {
            id: "preview-a",
            studentId: "a",
            institutionalId: "SV2026001",
            displayName: "Sinh viên Nguyễn Văn A",
            status: AttendanceStatus.Present,
            checkedInAt: "2026-06-29T08:05:00.000Z",
          },
          {
            id: "preview-b",
            studentId: "b",
            institutionalId: "SV2026002",
            displayName: "Sinh viên Trần Thị B",
            status: AttendanceStatus.Pending,
            checkedInAt: null,
            spoofSuspected: true,
          },
        ]
      : []);

  const records = useMemo(() => {
    const filtered = filterMonitorRecords(sourceRecords, statusFilter);
    return sortMonitorRecords(filtered, sortColumn, sortDirection);
  }, [sourceRecords, statusFilter, sortColumn, sortDirection]);

  function handleSort(column: MonitorSortColumn) {
    const nextDirection: MonitorSortDirection =
      sortColumn === column && sortDirection === "asc" ? "desc" : "asc";
    setSortColumn(column);
    setSortDirection(nextDirection);
    if (sessionId) {
      writeStoredSort(sessionId, column, nextDirection);
    }
  }

  const lastUpdatedMs =
    monitorQuery.dataUpdatedAt > 0 ? monitorQuery.dataUpdatedAt : undefined;

  const liveSummaryText = `Đã điểm danh ${summary.present} trên ${summary.enrolled}`;

  return (
    <div className="flex flex-col gap-4" data-testid="session-monitor-dashboard">
      {monitorQuery.isLoading && sessionId ? (
        <div className="flex items-center gap-2 text-small text-text-secondary">
          <Spinner className="h-4 w-4" />
          Đang tải dữ liệu buổi học…
        </div>
      ) : null}

      <div
        className="flex flex-wrap items-center justify-between gap-2 text-small text-text-secondary"
        data-testid="monitor-poll-status"
      >
        {monitorQuery.isError ? (
          <span className="text-danger-600">Không thể cập nhật — thử lại</span>
        ) : lastUpdatedMs ? (
          <span>Cập nhật lúc {formatPollTime(lastUpdatedMs)}</span>
        ) : (
          <span>Đang chờ dữ liệu…</span>
        )}
        {monitorQuery.isError ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => void monitorQuery.refetch()}
          >
            Thử lại
          </Button>
        ) : null}
      </div>

      <div
        className="grid grid-cols-3 gap-3"
        aria-live="polite"
        aria-atomic="true"
        data-testid="monitor-stat-cards"
      >
        <StatCard
          label="Đã điểm danh"
          value={String(summary.present)}
          sublabel={`/ ${summary.enrolled}`}
          testId="stat-card-present"
        />
        <StatCard
          label="Chưa điểm danh"
          value={String(summary.pending)}
          testId="stat-card-pending"
        />
        <StatCard
          label="Vắng"
          value={String(summary.absent)}
          testId="stat-card-absent"
        />
      </div>
      <p className="sr-only" data-testid="monitor-live-summary">
        {liveSummaryText}
      </p>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-small text-text-secondary">
          Trạng thái
          <select
            className="rounded-md border border-border bg-surface px-2 py-1 text-body text-text-primary"
            data-testid="monitor-status-filter"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.target.value as MonitorStatusFilter)
            }
          >
            {statusFilterOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {codeSharingAlert ? (
        <Alert variant="warning" title="Cảnh báo chia sẻ mã QR" data-testid="code-sharing-alert">
          Phát hiện thử sử dụng mã QR đã được quét. Yêu cầu sinh viên quét mã mới trên màn hình
          giảng viên.
        </Alert>
      ) : null}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-body">
          <thead>
            <tr className="border-b border-border text-small text-text-secondary">
              <th className="py-2">Mã SV</th>
              <th className="py-2">
                <SortableHeader
                  label="Họ tên"
                  active={sortColumn === "displayName"}
                  direction={sortDirection}
                  onSort={() => handleSort("displayName")}
                />
              </th>
              <th className="py-2">
                <SortableHeader
                  label="Trạng thái"
                  active={sortColumn === "status"}
                  direction={sortDirection}
                  onSort={() => handleSort("status")}
                  testId="monitor-sort-status"
                />
              </th>
              <th className="py-2">Thời gian</th>
              <th className="py-2">Ghi chú</th>
            </tr>
          </thead>
          <tbody>
            {records.length === 0 ? (
              <tr>
                <td colSpan={5} className="py-4 text-center text-text-secondary">
                  Chưa có dữ liệu điểm danh
                </td>
              </tr>
            ) : (
              records.map((record) => (
                <tr
                  key={record.id}
                  className="border-b border-border"
                  data-testid={`monitor-row-${record.institutionalId.toLowerCase()}`}
                >
                  <td className="py-2 font-mono text-small">{record.institutionalId}</td>
                  <td className="py-2">{record.displayName}</td>
                  <td className="py-2">
                    <StatusBadge status={record.status as AttendanceStatus} size="sm" />
                  </td>
                  <td className="py-2 text-small text-text-secondary">
                    {record.checkedInAt
                      ? formatMonitorTimestamp(record.checkedInAt)
                      : "—"}
                  </td>
                  <td className="py-2">
                    {record.spoofSuspected ? <SpoofAlertBadge /> : "—"}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sublabel,
  testId,
}: {
  label: string;
  value: string;
  sublabel?: string;
  testId: string;
}) {
  return (
    <div
      className="rounded-md border border-border bg-surface-raised p-3"
      data-testid={testId}
    >
      <p className="text-small text-text-secondary">{label}</p>
      <p className="text-h2 font-semibold">
        {value}
        {sublabel ? (
          <span className="text-body font-normal text-text-secondary"> {sublabel}</span>
        ) : null}
      </p>
    </div>
  );
}

function SortableHeader({
  label,
  active,
  direction,
  onSort,
  testId,
}: {
  label: string;
  active: boolean;
  direction: MonitorSortDirection;
  onSort: () => void;
  testId?: string;
}) {
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 font-medium text-text-secondary hover:text-text-primary"
      onClick={onSort}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
      data-testid={testId}
    >
      {label}
      <span aria-hidden="true">{active ? (direction === "asc" ? "↑" : "↓") : "↕"}</span>
    </button>
  );
}
