import type { AttendanceStatus } from "@wecheck/domain";
import { useEffect, useState } from "react";
import { Spinner } from "@/components/ui/spinner";
import { StatusBadge } from "@/components/ui/status-badge";
import {
  fetchAttendanceAuditLogs,
  type AttendanceAuditEntry,
} from "@/lib/attendance-roster-api";
import { formatMonitorTimestamp } from "@/lib/session-monitor-roster";

export interface AttendanceAuditTrailProps {
  recordId: string;
  /** Optimistic entry shown immediately after a successful edit */
  optimisticEntry?: AttendanceAuditEntry | null;
}

/** FR-11 / BR-10 / NFR-15 — read-only audit log panel for edited rows */
export function AttendanceAuditTrail({
  recordId,
  optimisticEntry,
}: AttendanceAuditTrailProps) {
  const [expanded, setExpanded] = useState(false);
  const [entries, setEntries] = useState<AttendanceAuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;
    setLoading(true);
    setError(false);

    void (async () => {
      try {
        const items = await fetchAttendanceAuditLogs(recordId);
        if (!cancelled) {
          setEntries(items);
        }
      } catch {
        if (!cancelled) {
          setError(true);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [expanded, recordId, optimisticEntry?.id]);

  const displayEntries = optimisticEntry
    ? [optimisticEntry, ...entries.filter((e) => e.id !== optimisticEntry.id)]
    : entries;

  return (
    <div data-testid={`attendance-audit-trail-${recordId}`}>
      <button
        type="button"
        className="text-small font-medium text-primary-700 hover:underline"
        aria-expanded={expanded}
        data-testid="attendance-audit-trail-toggle"
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? "Ẩn nhật ký chỉnh sửa" : "Xem nhật ký chỉnh sửa"}
      </button>

      {expanded ? (
        <div
          className="mt-2 rounded-md border border-border bg-surface-raised p-3"
          data-testid="attendance-audit-trail-panel"
        >
          {loading ? (
            <div className="flex items-center gap-2 text-small text-text-secondary">
              <Spinner className="h-4 w-4" />
              Đang tải nhật ký…
            </div>
          ) : null}

          {error ? (
            <p className="text-small text-danger-600">Không thể tải nhật ký chỉnh sửa.</p>
          ) : null}

          {!loading && !error && displayEntries.length === 0 ? (
            <p className="text-small text-text-secondary">Chưa có chỉnh sửa thủ công.</p>
          ) : null}

          {!loading && displayEntries.length > 0 ? (
            <ul className="space-y-3">
              {displayEntries.map((entry) => (
                <li
                  key={entry.id}
                  className="text-small"
                  data-testid={`audit-entry-${entry.id}`}
                >
                  <p className="font-medium text-text-primary">{entry.editorDisplayName}</p>
                  <p className="text-text-secondary">
                    {formatMonitorTimestamp(entry.editedAt)}
                  </p>
                  <p className="mt-1 flex flex-wrap items-center gap-2">
                    <StatusBadge status={entry.previousStatus as AttendanceStatus} size="sm" />
                    <span aria-hidden="true">→</span>
                    <StatusBadge status={entry.newStatus as AttendanceStatus} size="sm" />
                  </p>
                  {entry.note ? (
                    <p className="mt-1 text-text-secondary" data-testid="audit-entry-note">
                      {entry.note}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
