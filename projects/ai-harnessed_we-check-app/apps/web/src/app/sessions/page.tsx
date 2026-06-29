import { SessionStatus } from "@wecheck/domain";
import { Plus } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/layout/page-header";
import { SessionCard } from "@/components/domain/session/session-card";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert } from "@/components/ui/alert";
import { useSessionsList } from "@/hooks/use-sessions-list";
import { sessionStatusLabels } from "@/lib/copy/status-labels";
import type { SessionListItem } from "@/lib/sessions-api";

function SessionSection({
  label,
  sessions,
}: {
  label: string;
  sessions: SessionListItem[];
}) {
  if (sessions.length === 0) return null;

  return (
    <section className="mb-6">
      <h2 className="mb-3 text-h2 font-semibold">{label}</h2>
      <ul className="flex flex-col gap-3">
        {sessions.map((session) => (
          <li key={session.id}>
            <SessionCard session={session} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function ListSkeleton() {
  return (
    <div className="flex flex-col gap-3" data-testid="sessions-list-loading" aria-busy="true">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

/** FR-04 / AC-04 — instructor session list from API */
export function SessionsListPage() {
  const query = useSessionsList();

  if (query.isLoading) {
    return (
      <div data-testid="sessions-list-page">
        <PageHeader
          title="Buổi học"
          description="Quản lý buổi học và điểm danh"
          actions={
            <Link
              to="/sessions/new"
              className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
            >
              Tạo buổi học
            </Link>
          }
        />
        <ListSkeleton />
      </div>
    );
  }

  if (query.isError) {
    return (
      <div data-testid="sessions-list-page">
        <PageHeader title="Buổi học" description="Quản lý buổi học và điểm danh" />
        <Alert variant="danger" title="Không thể tải danh sách">
          Vui lòng thử lại sau.
        </Alert>
      </div>
    );
  }

  const items = query.data?.items ?? [];

  if (items.length === 0) {
    return (
      <div data-testid="sessions-list-page">
        <PageHeader title="Buổi học" description="Quản lý buổi học và điểm danh" />
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
      </div>
    );
  }

  const active = items.filter((s) => s.status === SessionStatus.Active);
  const draft = items.filter((s) => s.status === SessionStatus.Draft);
  const closed = items.filter(
    (s) => s.status === SessionStatus.Closed || s.status === SessionStatus.Cancelled,
  );

  return (
    <div data-testid="sessions-list-page">
      <PageHeader
        title="Buổi học"
        description="Quản lý buổi học và điểm danh"
        actions={
          <Link
            to="/sessions/new"
            className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
            data-testid="create-session-link"
          >
            Tạo buổi học
          </Link>
        }
      />
      <SessionSection label={sessionStatusLabels[SessionStatus.Active]} sessions={active} />
      <SessionSection label={sessionStatusLabels[SessionStatus.Draft]} sessions={draft} />
      <SessionSection label={sessionStatusLabels[SessionStatus.Closed]} sessions={closed} />
    </div>
  );
}
