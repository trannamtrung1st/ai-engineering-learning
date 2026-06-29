import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { SessionStatus } from "@wecheck/domain";
import { useQueryClient } from "@tanstack/react-query";
import { Alert } from "@/components/ui/alert";
import { QrCountdown } from "@/components/ui/qr-countdown";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusBadge } from "@/components/ui/status-badge";
import { useLiveCountdown } from "@/hooks/use-live-countdown";
import { useQrTokenPoll } from "@/hooks/use-qr-token-poll";
import { useSessionDetail } from "@/hooks/use-session-detail";
import { PageHeader } from "@/components/layout/page-header";
import { SessionMonitorDashboard } from "@/components/domain/session/session-monitor-dashboard";
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

function QrTabContent({
  sessionId,
  sessionStatus,
}: {
  sessionId: string;
  sessionStatus: SessionStatus;
}) {
  const [tokenKey, setTokenKey] = useState(0);
  const [fading, setFading] = useState(false);
  const qrQuery = useQrTokenPoll(
    sessionId,
    sessionStatus === SessionStatus.Active,
  );
  const liveToken = qrQuery.data;

  const handleCycleComplete = () => {
    setFading(true);
    void qrQuery.refetch();
    window.setTimeout(() => {
      setTokenKey((k) => k + 1);
      setFading(false);
    }, 300);
  };

  const { secondsRemaining } = useLiveCountdown({
    onCycleComplete: handleCycleComplete,
    syncSeconds: liveToken?.secondsRemaining,
    active: sessionStatus === SessionStatus.Active,
  });

  useEffect(() => {
    if (liveToken?.tokenId) {
      setTokenKey((k) => k + 1);
    }
  }, [liveToken?.tokenId]);

  if (sessionStatus === SessionStatus.Draft) {
    return (
      <div className="py-8 text-center" data-testid="session-not-active">
        <p className="text-body text-text-secondary">Buổi học chưa mở</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center gap-6 py-6">
      <div
        key={tokenKey}
        data-testid="qr-code-image"
        data-token-id={liveToken?.tokenId}
        data-token-key={tokenKey}
        className={`flex aspect-square w-64 items-center justify-center rounded-lg bg-surface-inverse transition-opacity duration-300 ${fading ? "opacity-0" : "opacity-100"}`}
        aria-label="Mã QR điểm danh buổi học"
      >
        <div className="grid grid-cols-8 gap-0.5 p-4">
          {Array.from({ length: 64 }, (_, i) => (
            <div
              key={i}
              className={`h-2 w-2 ${(i + tokenKey) % 3 === 0 ? "bg-qr-fg" : "bg-transparent"}`}
            />
          ))}
        </div>
      </div>
      <QrCountdown secondsRemaining={secondsRemaining} />
      <a
        href={`/sessions/${sessionId}/qr-present`}
        className="inline-flex min-h-touch items-center justify-center rounded-md border border-border bg-surface-raised px-4 font-medium hover:bg-primary-50"
      >
        Trình chiếu QR
      </a>
    </div>
  );
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
        <QrTabContent sessionId={id} sessionStatus={session.status} />
      ) : null}

      {tab === "monitor" ? (
        <div className="flex flex-col gap-4">
          {session.status === SessionStatus.Closed ? (
            <Alert variant="info" title="Buổi học đã kết thúc">
              Buổi học đã kết thúc. Dữ liệu điểm danh không còn cập nhật.
            </Alert>
          ) : null}
          <SessionMonitorDashboard sessionId={id ?? undefined} />
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
