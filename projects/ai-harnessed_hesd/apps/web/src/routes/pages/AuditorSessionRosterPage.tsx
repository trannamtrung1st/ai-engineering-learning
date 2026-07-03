import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router-dom";
import { LiveRosterPanel } from "../../components/domain/LiveRosterPanel";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fetchCurrentUser } from "../../lib/api/me-api";
import { canAccessAuditLogs } from "../../lib/auth/role-guard";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import styles from "./AuditorSessionRosterPage.module.css";

export function AuditorSessionRosterPage() {
  const { sessionId = "" } = useParams();
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    void (async () => {
      const me = await fetchCurrentUser();
      setAllowed(me.ok && canAccessAuditLogs(me.roles));
    })();
  }, []);

  if (!isStaffAuthenticated()) {
    return (
      <Navigate to={buildStaffLoginRedirect(`/audit/sessions/${sessionId}/roster`)} replace />
    );
  }

  if (allowed === false) {
    return (
      <ContentSection title="Danh sách buổi học">
        <FeedbackAlert variant="danger" title="Không có quyền truy cập">
          Bạn không có quyền xem danh sách điểm danh cho mục đích audit.
        </FeedbackAlert>
      </ContentSection>
    );
  }

  if (!sessionId) {
    return <Navigate to="/audit/logs" replace />;
  }

  if (allowed === null) {
    return <div className={styles.page} aria-busy="true" data-testid="auditor-roster-loading" />;
  }

  return (
    <div className={styles.page}>
      <Link className={styles.backLink} to="/audit/logs">
        ← Nhật ký audit
      </Link>
      <ContentSection title="Danh sách buổi học">
        <p className={styles.readOnlyBanner}>
          <StatusBadge label="Chỉ đọc · không có thao tác điều chỉnh" variant="brand" pill />
        </p>
        <LiveRosterPanel sessionId={sessionId} readOnly />
      </ContentSection>
    </div>
  );
}
