import { SessionStatus } from "@wecheck/domain";
import { Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { sessionStatusLabels } from "@/lib/copy/status-labels";
import { PREVIEW_SESSION_IDS } from "@/lib/preview-fixtures";

const demoSessions = {
  active: [
    { id: PREVIEW_SESSION_IDS.active, title: "SWE-101 — Buổi 5", className: "HESD-01" },
  ],
  draft: [
    { id: PREVIEW_SESSION_IDS.draft, title: "DB-201 — Buổi 3", className: "HESD-02" },
  ],
  closed: [
    { id: PREVIEW_SESSION_IDS.closed, title: "NET-301 — Buổi 1", className: "HESD-01" },
  ],
};

function SessionSection({
  label,
  status,
  sessions,
}: {
  label: string;
  status: SessionStatus;
  sessions: { id: string; title: string; className: string }[];
}) {
  if (sessions.length === 0) return null;

  return (
    <section className="mb-6">
      <h2 className="mb-3 text-h2 font-semibold">{label}</h2>
      <ul className="flex flex-col gap-3">
        {sessions.map((session) => (
          <li key={session.id}>
            <Link
              to={`/sessions/${session.id}`}
              className="flex items-center justify-between rounded-md border border-border bg-surface-raised p-4 hover:border-primary-500"
            >
              <div>
                <p className="font-medium">{session.title}</p>
                <p className="text-small text-text-secondary">{session.className}</p>
              </div>
              <StatusBadge status={status} />
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** NFR-17 / FR-04 — instructor session list shell */
export function SessionsListPage() {
  const [searchParams] = useSearchParams();
  const view = searchParams.get("view") ?? "populated";

  if (view === "empty") {
    return (
      <EmptyState
        icon={Plus}
        title="Chưa có buổi học"
        description="Tạo buổi học mới để bắt đầu điểm danh."
        action={
          <Link
            to="/sessions/new"
            className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
          >
            Tạo buổi học
          </Link>
        }
      />
    );
  }

  return (
    <div data-testid="sessions-list-page">
      <SessionSection
        label={sessionStatusLabels[SessionStatus.Active]}
        status={SessionStatus.Active}
        sessions={demoSessions.active}
      />
      <SessionSection
        label={sessionStatusLabels[SessionStatus.Draft]}
        status={SessionStatus.Draft}
        sessions={demoSessions.draft}
      />
      <SessionSection
        label={sessionStatusLabels[SessionStatus.Closed]}
        status={SessionStatus.Closed}
        sessions={demoSessions.closed}
      />
    </div>
  );
}
