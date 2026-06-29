import { SessionStatus } from "@wecheck/domain";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/ui/status-badge";
import type { SessionListItem } from "@/lib/sessions-api";

function formatSchedule(iso: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

export interface SessionCardProps {
  session: SessionListItem;
}

/** FR-04 / AC-04 — instructor session list card */
export function SessionCard({ session }: SessionCardProps) {
  const classSubject = `${session.classCode} · ${session.subjectCode}`;
  const showProgress =
    session.status === SessionStatus.Active &&
    session.enrollmentCount !== undefined &&
    session.enrollmentCount > 0;

  return (
    <Link
      to={`/sessions/${session.id}`}
      className="flex items-center justify-between rounded-md border border-border bg-surface-raised p-4 hover:border-primary-500"
      data-testid={`session-card-${session.id}`}
    >
      <div className="min-w-0 flex-1 pr-3">
        <p className="truncate font-medium">{session.title}</p>
        <p className="text-small text-text-secondary">{classSubject}</p>
        <p className="text-small text-text-secondary">
          {formatSchedule(session.scheduledStart)} · {session.roomName}
        </p>
        {showProgress ? (
          <div className="mt-2">
            <div
              className="h-1.5 w-full max-w-[200px] overflow-hidden rounded-full bg-surface-muted"
              role="progressbar"
              aria-valuenow={session.presentCount ?? 0}
              aria-valuemin={0}
              aria-valuemax={session.enrollmentCount}
              aria-label="Tiến độ điểm danh"
            >
              <div
                className="h-full bg-primary-600 transition-all"
                style={{
                  width: `${Math.round(((session.presentCount ?? 0) / session.enrollmentCount!) * 100)}%`,
                }}
              />
            </div>
            <p className="mt-1 text-small text-text-secondary">
              {session.presentCount ?? 0}/{session.enrollmentCount} đã điểm danh
            </p>
          </div>
        ) : null}
      </div>
      <StatusBadge status={session.status} />
    </Link>
  );
}
