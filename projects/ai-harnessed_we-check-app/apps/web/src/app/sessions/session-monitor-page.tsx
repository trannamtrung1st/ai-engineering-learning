import { useParams } from "react-router-dom";
import { PageHeader } from "@/components/layout/page-header";
import { SessionMonitorDashboard } from "@/components/domain/session/session-monitor-dashboard";
import { resolvePreviewId } from "@/lib/preview-fixtures";

/** FR-15 / AC-10 — dedicated monitor route per test cases /sessions/:id/monitor */
export function SessionMonitorPage() {
  const { id: routeId } = useParams<{ id: string }>();
  const id = resolvePreviewId(routeId) ?? routeId;

  return (
    <div data-testid="session-monitor-page">
      <PageHeader
        title={`Theo dõi buổi học ${id ?? ""}`}
        description="HESD-01 · SWE-101"
      />
      <SessionMonitorDashboard sessionId={id ?? undefined} />
    </div>
  );
}
