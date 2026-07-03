import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { AuditLogList } from "../../components/domain/AuditLogList";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { StatusBadge } from "../../components/ui/StatusBadge";
import { fetchCurrentUser } from "../../lib/api/me-api";
import { canAccessAuditLogs, isReadOnlyStaffRole } from "../../lib/auth/role-guard";
import { getAccessToken } from "../../lib/auth/session";
import { buildStaffLoginRedirect } from "../../lib/auth/staff-gate";
import styles from "./AuditLogPage.module.css";

export function AuditLogPage() {
  const [roles, setRoles] = useState<string[] | null>(null);
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    void (async () => {
      if (!getAccessToken()) {
        setRoles([]);
        return;
      }
      const me = await fetchCurrentUser();
      if (!me.ok) {
        setRoles([]);
        return;
      }
      setRoles(me.roles);
      if (!canAccessAuditLogs(me.roles)) {
        setAccessDenied(true);
      }
    })();
  }, []);

  if (roles === null) {
    return <div className={styles.loading} aria-busy="true" />;
  }

  if (accessDenied || !canAccessAuditLogs(roles)) {
    return (
      <ContentSection>
        <FeedbackAlert variant="danger" title="Không có quyền truy cập">
          Bạn không có quyền xem nhật ký audit. Sinh viên vui lòng sử dụng{" "}
          <a href="/me/attendance">lịch sử điểm danh cá nhân</a>.
        </FeedbackAlert>
      </ContentSection>
    );
  }

  const readOnly = isReadOnlyStaffRole(roles);

  return (
    <ContentSection>
      {readOnly ? (
        <div className={styles.badge}>
          <StatusBadge label="Chế độ chỉ đọc · SystemAuditor" variant="brand" pill />
        </div>
      ) : null}
      <AuditLogList readOnly={readOnly} />
    </ContentSection>
  );
}

export function AuditLogPageGuard() {
  if (!getAccessToken()) {
    return <Navigate to={buildStaffLoginRedirect("/audit/logs")} replace />;
  }
  return <AuditLogPage />;
}
