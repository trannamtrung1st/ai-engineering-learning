import { useCallback, useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { LiveRosterPanel } from "../../components/domain/LiveRosterPanel";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import {
  fetchClassSessionById,
  formatSessionLabel,
  type ClassSessionSummary,
} from "../../lib/api/session-api";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import styles from "./LecturerRosterPage.module.css";

export function LecturerRosterPage() {
  const { sessionId = "" } = useParams();
  const [session, setSession] = useState<ClassSessionSummary | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadSession = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    setLoadError(null);
    const result = await fetchClassSessionById(sessionId);
    if (result.ok) {
      setSession(result.session);
    } else {
      setSession(null);
      setLoadError(result.message);
    }
    setLoading(false);
  }, [sessionId]);

  useEffect(() => {
    void loadSession();
  }, [loadSession]);

  if (!isStaffAuthenticated()) {
    return <Navigate to={buildStaffLoginRedirect(`/lecturer/sessions/${sessionId}/roster`)} replace />;
  }

  if (!sessionId) {
    return <Navigate to="/lecturer/sessions" replace />;
  }

  if (loading) {
    return <div className={styles.page} aria-busy="true" data-testid="roster-page-loading" />;
  }

  if (loadError || !session) {
    return (
      <div className={styles.page}>
        <FeedbackAlert variant="danger" title="Không có quyền truy cập">
          Buổi học không tồn tại hoặc bạn không được phép xem danh sách điểm danh.
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
        <Link className={styles.sessionLink} to={`/lecturer/sessions/${sessionId}`}>
          Mã QR · {formatSessionLabel(session)}
        </Link>
      </div>

      <ContentSection title="Danh sách điểm danh trực tiếp" titleClassName={styles.backLink}>
        <LiveRosterPanel sessionId={sessionId} sectionCode={session.sectionCode} />
      </ContentSection>
    </div>
  );
}
