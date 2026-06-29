import {
  AttendanceStatus,
  SessionStatus,
  type UserRole,
} from "@wecheck/domain";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { AttendanceAuditTrail } from "@/components/domain/attendance/attendance-audit-trail";
import { AttendanceEditDialog } from "@/components/instructor/attendance-edit-dialog";
import { useAuthUser } from "@/components/auth/require-auth";
import { useInvalidateSessionRoster, useSessionRoster } from "@/hooks/use-session-roster";
import type { AttendanceAuditEntry, RosterRecord } from "@/lib/attendance-roster-api";
import {
  instructorEditHoursRemaining,
  isAttendanceEditAllowed,
} from "@/lib/attendance-edit-window";
import {
  filterMonitorRecords,
  formatMonitorTimestamp,
  sortMonitorRecords,
  type MonitorSortColumn,
  type MonitorSortDirection,
  type MonitorStatusFilter,
} from "@/lib/session-monitor-roster";

export interface AttendanceRosterTableProps {
  sessionId: string;
  sessionStatus: SessionStatus;
  closedAt: string | null;
}

const statusFilterOptions: Array<{ value: MonitorStatusFilter; label: string }> = [
  { value: "all", label: "Tất cả" },
  { value: AttendanceStatus.Present, label: "Có mặt" },
  { value: AttendanceStatus.Absent, label: "Vắng" },
  { value: AttendanceStatus.Pending, label: "Chưa điểm danh" },
  { value: AttendanceStatus.Excused, label: "Vắng có phép" },
  { value: AttendanceStatus.Rejected, label: "Từ chối" },
];

/** FR-11 / AC-11 / BR-10 — full attendance roster with manual edit */
export function AttendanceRosterTable({
  sessionId,
  sessionStatus,
  closedAt,
}: AttendanceRosterTableProps) {
  const user = useAuthUser();
  const rosterQuery = useSessionRoster(sessionId);
  const invalidateRoster = useInvalidateSessionRoster();

  const [statusFilter, setStatusFilter] = useState<MonitorStatusFilter>("all");
  const [sortColumn, setSortColumn] = useState<MonitorSortColumn>("displayName");
  const [sortDirection, setSortDirection] = useState<MonitorSortDirection>("asc");
  const [editingRecord, setEditingRecord] = useState<RosterRecord | null>(null);
  const [optimisticAudits, setOptimisticAudits] = useState<
    Record<string, AttendanceAuditEntry>
  >({});

  const editAllowed = isAttendanceEditAllowed({
    editorRole: user.role as UserRole,
    sessionStatus,
    closedAt,
  });

  const windowExpired =
    user.role === "Instructor" &&
    sessionStatus === SessionStatus.Closed &&
    !editAllowed;

  const hoursRemaining =
    user.role === "Instructor" && sessionStatus === SessionStatus.Closed
      ? instructorEditHoursRemaining(closedAt)
      : null;

  const records = useMemo(() => {
    const source = rosterQuery.data?.records ?? [];
    const filtered = filterMonitorRecords(source, statusFilter);
    return sortMonitorRecords(filtered, sortColumn, sortDirection);
  }, [rosterQuery.data?.records, statusFilter, sortColumn, sortDirection]);

  function handleSort(column: MonitorSortColumn) {
    const nextDirection: MonitorSortDirection =
      sortColumn === column && sortDirection === "asc" ? "desc" : "asc";
    setSortColumn(column);
    setSortDirection(nextDirection);
  }

  function handleSaved(record: RosterRecord, note: string, previousStatus: string) {
    toast.success("Đã cập nhật điểm danh");
    setOptimisticAudits((prev) => ({
      ...prev,
      [record.id]: {
        id: `optimistic-${record.id}-${Date.now()}`,
        editorId: user.id,
        editorDisplayName: user.displayName,
        previousStatus: previousStatus as AttendanceStatus,
        newStatus: record.status as AttendanceStatus,
        note: note || null,
        editedAt: new Date().toISOString(),
      },
    }));
    invalidateRoster(sessionId);
  }

  if (rosterQuery.isLoading) {
    return (
      <div data-testid="attendance-roster-table">
        <Skeleton className="mb-4 h-10 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (rosterQuery.isError) {
    return (
      <Alert variant="danger" title="Không thể tải danh sách điểm danh">
        Vui lòng thử lại sau.
      </Alert>
    );
  }

  return (
    <div className="flex flex-col gap-4" data-testid="attendance-roster-table">
      {sessionStatus === SessionStatus.Closed && user.role === "Instructor" ? (
        <p
          className="text-small text-text-secondary"
          data-testid="roster-edit-window-notice"
        >
          {windowExpired
            ? "Đã hết thời hạn chỉnh sửa điểm danh (24 giờ). Chỉ phòng đào tạo có thể chỉnh sửa sau thời hạn này."
            : hoursRemaining !== null && hoursRemaining > 0
              ? `Còn ${hoursRemaining} giờ để chỉnh sửa điểm danh sau khi đóng buổi học.`
              : "Chỉ phòng đào tạo có thể chỉnh sửa sau 24 giờ"}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-small text-text-secondary">
          Lọc trạng thái
          <select
            className="rounded-md border border-border bg-surface px-2 py-1 text-body text-text-primary"
            data-testid="roster-status-filter"
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

      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-body">
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
                  testId="roster-sort-status"
                />
              </th>
              <th className="py-2">Thời gian</th>
              <th className="py-2">Thao tác</th>
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
              records.map((record) => {
                const rowEditAllowed = editAllowed;
                const showAudit =
                  optimisticAudits[record.id] !== undefined ||
                  record.status !== AttendanceStatus.Pending;

                return (
                  <tr
                    key={record.id}
                    className="border-b border-border align-top"
                    data-testid={`roster-row-${record.institutionalId.toLowerCase()}`}
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
                      <div className="flex flex-col gap-2">
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          disabled={!rowEditAllowed}
                          aria-label={`Chỉnh sửa điểm danh ${record.displayName}`}
                          data-testid={`roster-edit-${record.institutionalId.toLowerCase()}`}
                          onClick={() => setEditingRecord(record)}
                        >
                          Chỉnh sửa
                        </Button>
                        {showAudit ? (
                          <AttendanceAuditTrail
                            recordId={record.id}
                            optimisticEntry={optimisticAudits[record.id] ?? null}
                          />
                        ) : null}
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <AttendanceEditDialog
        open={editingRecord !== null}
        record={editingRecord}
        editAllowed={editAllowed}
        windowExpired={windowExpired}
        hoursRemaining={hoursRemaining}
        onClose={() => setEditingRecord(null)}
        onSaved={(record, note) => {
          const previousStatus = editingRecord?.status ?? record.status;
          handleSaved(record, note, previousStatus);
        }}
      />
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
