import { useId, useState } from "react";
import { Link } from "react-router-dom";
import type { AuditLogEntry } from "../../lib/api/audit-api";
import { formatCheckInTimestamp } from "../../lib/check-in/format-timestamp";
import { formatAuditActionType } from "../../lib/i18n/audit-action-types";
import { auditLogsQueryToSearchParams } from "../../lib/listing/audit-logs-list-query";
import styles from "./AuditEntryRow.module.css";

export interface AuditEntryRowProps {
  entry: AuditLogEntry;
  readOnly?: boolean;
}

function buildStatusChange(entry: AuditLogEntry): string | null {
  if (entry.oldStatus || entry.newStatus) {
    return `${entry.oldStatus ?? "—"} → ${entry.newStatus ?? "—"}`;
  }
  if (entry.outcome) {
    return entry.outcome;
  }
  return null;
}

function buildExportSummary(entry: AuditLogEntry): string | null {
  if (entry.actionType !== "Export") return null;
  const parts: string[] = [];
  if (entry.format) parts.push(entry.format);
  if (entry.scopeFilterSummary) parts.push(entry.scopeFilterSummary);
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** Traceability: FR-29 FR-30 FR-32 BR-22 AC-19 */
export function AuditEntryRow({ entry, readOnly = true }: AuditEntryRowProps) {
  const [expanded, setExpanded] = useState(false);
  const panelId = useId();
  const actorLabel = entry.actorDisplayName ?? entry.actorUserId?.slice(0, 8) ?? "Hệ thống";
  const changeSummary = buildStatusChange(entry) ?? buildExportSummary(entry);

  return (
    <article className={styles.auditEntryRow} data-testid={`audit-entry-${entry.id}`}>
      <button
        type="button"
        className={styles.summaryRow}
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((value) => !value)}
      >
        <div className={styles.cellPrimary}>
          <span className={styles.actionType}>{formatAuditActionType(entry.actionType)}</span>
          <span className={styles.meta}>
            {actorLabel}
            {entry.actorRole ? ` · ${entry.actorRole}` : ""}
          </span>
        </div>
        <div>
          <span className={styles.meta}>{entry.targetType}</span>
          <div className={styles.meta}>{entry.targetId.slice(0, 8)}</div>
        </div>
        <div className={styles.changeSummary}>{changeSummary ?? "—"}</div>
        <div className={styles.timestamp}>{formatCheckInTimestamp(entry.occurredAt)}</div>
        <span className={styles.expandIcon} aria-hidden="true">
          {expanded ? "▾" : "▸"}
        </span>
      </button>

      {expanded ? (
        <div id={panelId} className={styles.detailPanel}>
          <div className={styles.detailGrid}>
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Thời điểm</span>
              <span className={styles.detailValue}>{formatCheckInTimestamp(entry.occurredAt)}</span>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Người thực hiện</span>
              <span className={styles.detailValue}>
                {actorLabel}
                {entry.actorUserId ? ` (${entry.actorUserId.slice(0, 8)})` : ""}
              </span>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Hành động</span>
              <span className={styles.detailValue}>{formatAuditActionType(entry.actionType)}</span>
            </div>
            <div className={styles.detailItem}>
              <span className={styles.detailLabel}>Đối tượng</span>
              <span className={styles.detailValue}>
                {entry.targetType} · {entry.targetId}
              </span>
            </div>
            {entry.oldStatus || entry.newStatus ? (
              <div className={styles.detailItem}>
                <span className={styles.detailLabel}>Trạng thái</span>
                <span className={styles.detailValue}>{buildStatusChange(entry)}</span>
              </div>
            ) : null}
            {entry.reason ? (
              <div className={styles.detailItem}>
                <span className={styles.detailLabel}>Lý do</span>
                <span className={styles.detailValue}>{entry.reason}</span>
              </div>
            ) : null}
            {entry.scopeFilterSummary ? (
              <div className={styles.detailItem}>
                <span className={styles.detailLabel}>Phạm vi</span>
                <span className={styles.detailValue}>{entry.scopeFilterSummary}</span>
              </div>
            ) : null}
            {entry.format ? (
              <div className={styles.detailItem}>
                <span className={styles.detailLabel}>Định dạng</span>
                <span className={styles.detailValue}>{entry.format}</span>
              </div>
            ) : null}
            {entry.correlationId ? (
              <div className={styles.detailItem}>
                <span className={styles.detailLabel}>Correlation</span>
                <span className={styles.detailValue}>{entry.correlationId.slice(0, 12)}</span>
              </div>
            ) : null}
          </div>

          <div className={styles.links}>
            {entry.classSessionId ? (
              <Link className={styles.link} to={`/audit/sessions/${entry.classSessionId}/roster`}>
                Xem danh sách buổi học
              </Link>
            ) : null}
            {entry.studentUserId ? (
              <Link
                className={styles.link}
                to={`/audit/logs?${auditLogsQueryToSearchParams({
                  targetId: entry.studentUserId,
                  sortBy: "timestamp",
                  sortOrder: "desc",
                  page: 1,
                  pageSize: 25,
                }).toString()}`}
              >
                Lọc theo sinh viên
              </Link>
            ) : null}
            {entry.targetId ? (
              <Link
                className={styles.link}
                to={`/audit/logs?${auditLogsQueryToSearchParams({
                  targetId: entry.targetId,
                  sortBy: "timestamp",
                  sortOrder: "desc",
                  page: 1,
                  pageSize: 25,
                }).toString()}`}
              >
                Lọc theo đối tượng
              </Link>
            ) : null}
          </div>

          {readOnly ? (
            <p className={styles.readOnlyNote}>
              Chế độ chỉ đọc — không có thao tác chỉnh sửa hoặc xóa bản ghi audit.
            </p>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
