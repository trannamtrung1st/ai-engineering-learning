import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { SessionStatus } from "@wecheck/domain";
import { useQueryClient } from "@tanstack/react-query";
import { Alert } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { useSessionDetail } from "@/hooks/use-session-detail";
import { PageHeader } from "@/components/layout/page-header";
import { SessionMonitorDashboard } from "@/components/domain/session/session-monitor-dashboard";
import { QrDisplayPanel } from "@/components/instructor/qr-display-panel";
import { SessionForm } from "@/components/instructor/session-form";
import { SessionLifecycleActions } from "@/components/instructor/session-lifecycle-actions";
import { resolvePreviewId } from "@/lib/preview-fixtures";
import type { SessionDetail } from "@/lib/sessions-api";

type SessionTab = "qr" | "monitor" | "roster" | "settings";

function formatSessionTimestamp(iso: string): string {
  return new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(iso));
}

const tabLabels: Record<SessionTab, string> = {
  qr: "Mã QR",
  monitor: "Theo dõi",
  roster: "Danh sách",
  settings: "Cài đặt",
};

function defaultTab(status: SessionStatus): SessionTab {
  if (status === SessionStatus.Draft) return "settings";
  if (status === SessionStatus.Active) return "monitor";
  return "settings";
}

/** FR-05 / AC-05 — session detail hub with lifecycle actions */
export function SessionDetailPage() {
  const { id: routeId } = useParams<{ id: string }>();
  const id = resolvePreviewId(routeId) ?? routeId;
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const sessionQuery = useSessionDetail(id);
  const session = sessionQuery.data;

  const [tab, setTab] = useState<SessionTab>(() => {
    const fromUrl = searchParams.get("tab") as SessionTab | null;
    if (fromUrl && fromUrl in tabLabels) return fromUrl;
    return "monitor";
  });

  useEffect(() => {
    if (!session) return;
    const fromUrl = searchParams.get("tab") as SessionTab | null;
    if (!fromUrl) {
      setTab(defaultTab(session.status));
    }
  }, [session, searchParams]);

  function handleTabChange(next: SessionTab) {
    setTab(next);
    setSearchParams({ tab: next }, { replace: true });
  }

  function handleSessionUpdated(updated: SessionDetail) {
    queryClient.setQueryData(["session", id], updated);
    void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    void queryClient.invalidateQueries({ queryKey: ["session-monitor", id] });
    if (updated.status === SessionStatus.Active && tab === "settings") {
      handleTabChange("monitor");
    }
  }

  if (sessionQuery.isLoading) {
    return (
      <div data-testid="session-detail-page">
        <Skeleton className="mb-4 h-10 w-2/3" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (sessionQuery.isError || !session) {
    return (
      <div data-testid="session-detail-page">
        <Alert variant="danger" title="Không thể tải buổi học">
          Buổi học không tồn tại hoặc bạn không có quyền truy cập.
        </Alert>
      </div>
    );
  }

  const metaLine = `${session.classCode} · ${session.subjectCode}`;

  return (
    <div data-testid="session-detail-page">
      <PageHeader
        title={session.title}
        description={`${metaLine} · ${session.roomName}`}
        actions={<StatusBadge status={session.status} />}
      />

      {session.openedAt ? (
        <p
          className="mb-2 text-small text-text-secondary"
          data-testid="session-opened-at"
        >
          Mở lúc: {formatSessionTimestamp(session.openedAt)}
        </p>
      ) : null}

      {session.roomLatitude !== null && session.roomLongitude !== null ? (
        <p
          className="mb-4 text-small text-text-secondary"
          data-testid="session-gps-coords"
        >
          GPS: {session.roomLatitude}, {session.roomLongitude} · Bán kính{" "}
          {session.gpsRadiusMeters} m
        </p>
      ) : null}

      <div className="mb-6 flex gap-2 border-b border-border" role="tablist">
        {(Object.keys(tabLabels) as SessionTab[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`px-4 py-2 text-body font-medium ${
              tab === key
                ? "border-b-2 border-primary-600 text-primary-700"
                : "text-text-secondary"
            }`}
            onClick={() => handleTabChange(key)}
          >
            {tabLabels[key]}
          </button>
        ))}
      </div>

      {tab === "qr" && id ? (
        <QrDisplayPanel
          sessionId={id}
          sessionStatus={session.status}
          classCode={session.classCode}
          subjectCode={session.subjectCode}
          roomName={session.roomName}
        />
      ) : null}

      {tab === "monitor" ? (
        <div className="flex flex-col gap-4">
          {session.status === SessionStatus.Closed ? (
            <Alert variant="info" title="Buổi học đã kết thúc">
              Buổi học đã kết thúc. Dữ liệu điểm danh không còn cập nhật.
            </Alert>
          ) : null}
          <SessionMonitorDashboard
            sessionId={id ?? undefined}
            pollingEnabled={session.status === SessionStatus.Active}
          />
        </div>
      ) : null}

      {tab === "roster" ? (
        <div>
          {session.status === SessionStatus.Closed ? (
            <p
              className="text-small text-text-secondary"
              title="Chỉ phòng đào tạo có thể chỉnh sửa sau 24 giờ"
            >
              Chỉ phòng đào tạo có thể chỉnh sửa sau 24 giờ
            </p>
          ) : (
            <p className="text-body">Danh sách điểm danh</p>
          )}
        </div>
      ) : null}

      {tab === "settings" ? (
        <div className="flex flex-col gap-8">
          <SessionLifecycleActions
            session={session}
            onSessionUpdated={handleSessionUpdated}
          />
          <SessionForm
            mode={session.status === SessionStatus.Draft ? "edit" : "view"}
            session={session}
            classCode={session.classCode}
            subjectCode={session.subjectCode}
            onSaved={(saved) => handleSessionUpdated({ ...session, ...saved })}
          />
        </div>
      ) : null}
    </div>
  );
}
