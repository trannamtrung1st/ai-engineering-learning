import { useCallback, useEffect, useRef, useState } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { QrDisplayPanel, type QrDisplayData } from "../../components/domain/QrDisplayPanel";
import { SessionControlBar } from "../../components/domain/SessionControlBar";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import {
  closeClassSession,
  fetchClassSessionById,
  fetchCurrentQr,
  formatRoomLabel,
  formatScheduledAt,
  formatSessionLabel,
  openClassSession,
  type ClassSessionSummary,
} from "../../lib/api/session-api";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import styles from "./LecturerSessionPage.module.css";

export function LecturerSessionPage() {
  const { sessionId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [session, setSession] = useState<ClassSessionSummary | null>(null);
  const [qrData, setQrData] = useState<QrDisplayData | null>(null);
  const [qrError, setQrError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [closeSummary, setCloseSummary] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const autoOpenHandled = useRef(false);

  const refreshQr = useCallback(async () => {
    if (!sessionId) return;
    const result = await fetchCurrentQr(sessionId);
    if (result.ok) {
      setQrData(result.qr);
      setQrError(null);
      return;
    }
    setQrData(null);
    setQrError(result.message);
  }, [sessionId]);

  const loadSession = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setLoadError(null);
    const result = await fetchClassSessionById(sessionId);
    if (result.ok) {
      setSession(result.session);
      if (result.session.state === "Open") {
        await refreshQr();
      } else {
        setQrData(null);
        setQrError(null);
      }
    } else {
      setSession(null);
      setLoadError(result.message);
    }
    setLoading(false);
  }, [refreshQr, sessionId]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  const handleOpen = useCallback(async () => {
    if (!sessionId) return;
    setMutating(true);
    setActionError(null);
    setCloseSummary(null);
    const result = await openClassSession(sessionId);
    if (result.ok) {
      setSession((current) =>
        current
          ? {
              ...current,
              state: "Open",
              openedAt: result.data.openedAt,
            }
          : current,
      );
      setQrData({
        qrPayload: result.data.qr.qrPayload,
        expiresAt: result.data.qr.expiresAt,
        tokenState: "Valid",
      });
      setQrError(null);
    } else {
      setActionError(result.message);
    }
    setMutating(false);
  }, [sessionId]);

  const handleClose = useCallback(async () => {
    if (!sessionId) return;
    setMutating(true);
    setActionError(null);
    const result = await closeClassSession(sessionId);
    if (result.ok) {
      setSession((current) =>
        current
          ? {
              ...current,
              state: "Closed",
              closedAt: result.data.closedAt,
            }
          : current,
      );
      setQrData(null);
      setQrError(null);
      const summary = result.data.summary;
      setCloseSummary(
        `Đã đóng buổi học · Có mặt ${summary.present}, muộn ${summary.late}, vắng ${summary.absent}`,
      );
    } else {
      setActionError(result.message);
    }
    setMutating(false);
  }, [sessionId]);

  useEffect(() => {
    if (
      searchParams.get("action") === "open" &&
      session?.state === "Scheduled" &&
      !autoOpenHandled.current &&
      !mutating
    ) {
      autoOpenHandled.current = true;
      const next = new URLSearchParams(searchParams);
      next.delete("action");
      setSearchParams(next, { replace: true });
      void handleOpen();
    }
  }, [handleOpen, mutating, searchParams, session?.state, setSearchParams]);

  if (!isStaffAuthenticated()) {
    return <Navigate to={buildStaffLoginRedirect(`/lecturer/sessions/${sessionId}`)} replace />;
  }

  if (!sessionId) {
    return <Navigate to="/lecturer/sessions" replace />;
  }

  if (loading) {
    return <div className={styles.page} aria-busy="true" data-testid="session-loading" />;
  }

  if (loadError || !session) {
    return (
      <div className={styles.page}>
        <FeedbackAlert variant="danger" title="Không thể tải buổi học">
          {loadError ?? "Buổi học không tồn tại hoặc bạn không có quyền truy cập."}
        </FeedbackAlert>
        <Link className={styles.backLink} to="/lecturer/sessions">
          Quay lại danh sách
        </Link>
      </div>
    );
  }

  return (
    <div className={styles.page}>
      <div className={styles.backRow}>
        <Link className={styles.backLink} to="/lecturer/sessions">
          ← Danh sách buổi học
        </Link>
      </div>

      {actionError ? (
        <FeedbackAlert variant="danger" title="Không thể cập nhật trạng thái">
          {actionError}
        </FeedbackAlert>
      ) : null}

      {closeSummary ? (
        <FeedbackAlert variant="success" title="Đóng buổi học thành công">
          {closeSummary}
        </FeedbackAlert>
      ) : null}

      <SessionControlBar
        className={styles.controlBar}
        sectionCode={session.sectionCode}
        roomName={formatRoomLabel(session)}
        scheduledAt={formatScheduledAt(session.scheduledStartAt)}
        sessionState={session.state}
        sessionId={session.classSessionId}
        openedAt={session.openedAt}
        onOpen={() => void handleOpen()}
        onClose={() => void handleClose()}
        loading={mutating}
      />

      <ContentSection title="Mã QR điểm danh" titleClassName={styles.sectionTitle}>
        <QrDisplayPanel
          sectionCode={session.sectionCode}
          sessionName={formatSessionLabel(session)}
          sessionState={session.state}
          qrData={qrData}
          errorMessage={qrError}
          projectionMode
          onRefresh={() => void refreshQr()}
          onExpire={() => void refreshQr()}
        />
      </ContentSection>
    </div>
  );
}
