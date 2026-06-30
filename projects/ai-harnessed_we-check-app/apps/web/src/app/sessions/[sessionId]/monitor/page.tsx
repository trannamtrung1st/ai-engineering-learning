import { SessionStatus } from "@wecheck/domain";
import { useParams } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/layout/page-header";
import { SessionMonitorDashboard } from "@/components/domain/session/session-monitor-dashboard";
import { useSessionDetail } from "@/hooks/use-session-detail";
import { resolvePreviewId } from "@/lib/preview-fixtures";

/** FR-15 / AC-15 / NFR-08 — dedicated monitor route at /sessions/:sessionId/monitor */
export function SessionMonitorPage() {
  const { sessionId: routeId } = useParams<{ sessionId: string }>();
  const sessionId = resolvePreviewId(routeId) ?? routeId;
  const sessionQuery = useSessionDetail(sessionId);
  const session = sessionQuery.data;

  if (sessionQuery.isLoading) {
    return (
      <div data-testid="session-monitor-page">
        <Skeleton className="mb-4 h-10 w-2/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (sessionQuery.isError || !session) {
    return (
      <div data-testid="session-monitor-page">
        <Alert variant="danger" title="Không thể tải buổi học">
          Buổi học không tồn tại hoặc bạn không có quyền truy cập.
        </Alert>
      </div>
    );
  }

  const metaLine = `${session.classCode} · ${session.subjectCode}`;

  return (
    <div data-testid="session-monitor-page">
      <PageHeader
        title={`Theo dõi — ${session.title}`}
        description={`${metaLine} · ${session.roomName}`}
      />
      {session.status === SessionStatus.Closed ? (
        <Alert variant="info" title="Buổi học đã kết thúc" className="mb-4">
          Buổi học đã kết thúc. Dữ liệu điểm danh không còn cập nhật.
        </Alert>
      ) : null}
      <SessionMonitorDashboard
        sessionId={sessionId ?? undefined}
        pollingEnabled={session.status === SessionStatus.Active}
      />
    </div>
  );
}
