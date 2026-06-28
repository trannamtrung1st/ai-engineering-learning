import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { SessionStatus } from "@wecheck/domain";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { QrCountdown } from "@/components/ui/qr-countdown";
import { StatusBadge } from "@/components/ui/status-badge";
import { useLiveCountdown } from "@/hooks/use-live-countdown";
import { useQrTokenPoll } from "@/hooks/use-qr-token-poll";
import { PageHeader } from "@/components/layout/page-header";
import { PREVIEW_SESSION_IDS, resolvePreviewId } from "@/lib/preview-fixtures";

type SessionTab = "qr" | "monitor" | "roster" | "settings";

const tabLabels: Record<SessionTab, string> = {
  qr: "Mã QR",
  monitor: "Theo dõi",
  roster: "Danh sách",
  settings: "Cài đặt",
};

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

/** NFR-17 / FR-05 / NFR-06 — session detail with tabs and lifecycle actions */
export function SessionDetailPage() {
  const { id: routeId } = useParams<{ id: string }>();
  const id = resolvePreviewId(routeId) ?? routeId;
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState<SessionTab>(
    (searchParams.get("tab") as SessionTab) ?? "qr",
  );
  const [showOpenConfirm, setShowOpenConfirm] = useState(false);
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const [sessionStatus, setSessionStatus] = useState<SessionStatus>(() => {
    if (id === PREVIEW_SESSION_IDS.draft) return SessionStatus.Draft;
    if (id === PREVIEW_SESSION_IDS.closed) return SessionStatus.Closed;
    return SessionStatus.Active;
  });

  return (
    <div data-testid="session-detail-page">
      <PageHeader
        title={`Buổi học ${id ?? ""}`}
        description="HESD-01 · SWE-101"
        actions={<StatusBadge status={sessionStatus} />}
      />

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
            onClick={() => setTab(key)}
          >
            {tabLabels[key]}
          </button>
        ))}
      </div>

      {tab === "qr" && id ? (
        <QrTabContent sessionId={id} sessionStatus={sessionStatus} />
      ) : null}

      {tab === "monitor" ? (
        <div>
          {sessionStatus === SessionStatus.Closed ? (
            <Alert variant="info" title="Buổi học đã kết thúc">
              Buổi học đã kết thúc. Dữ liệu điểm danh không còn cập nhật.
            </Alert>
          ) : (
            <p className="text-body">Theo dõi điểm danh trực tiếp</p>
          )}
        </div>
      ) : null}

      {tab === "roster" ? (
        <div>
          {sessionStatus === SessionStatus.Closed ? (
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
        <div className="flex flex-col gap-3">
          {sessionStatus === SessionStatus.Draft ? (
            <>
              <Button type="button" onClick={() => setShowOpenConfirm(true)}>
                Mở buổi học
              </Button>
              <Button type="button" variant="danger">
                Hủy buổi học
              </Button>
            </>
          ) : sessionStatus === SessionStatus.Active ? (
            <Button type="button" onClick={() => setShowCloseConfirm(true)}>
              Đóng buổi học
            </Button>
          ) : null}
        </div>
      ) : null}

      {showOpenConfirm ? (
        <div
          role="dialog"
          aria-labelledby="open-confirm-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        >
          <div className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg">
            <h2 id="open-confirm-title" className="text-h2 font-semibold">
              Xác nhận mở buổi học?
            </h2>
            <p className="mt-2 text-body text-text-secondary">
              Sau khi mở, sinh viên có thể bắt đầu điểm danh bằng mã QR.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setShowOpenConfirm(false)}>
                Hủy
              </Button>
              <Button
                type="button"
                onClick={() => {
                  setSessionStatus(SessionStatus.Active);
                  setShowOpenConfirm(false);
                  setTab("monitor");
                }}
              >
                Mở buổi học
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {showCloseConfirm ? (
        <div
          role="dialog"
          aria-labelledby="close-confirm-title"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
        >
          <div className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg">
            <h2 id="close-confirm-title" className="text-h2 font-semibold">
              Kết thúc điểm danh?
            </h2>
            <p className="mt-2 text-body text-text-secondary">
              Sinh viên chưa điểm danh sẽ được ghi nhận vắng mặt.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setShowCloseConfirm(false)}>
                Hủy
              </Button>
              <Button
                type="button"
                onClick={() => {
                  setSessionStatus(SessionStatus.Closed);
                  setShowCloseConfirm(false);
                }}
              >
                Đóng buổi học
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
