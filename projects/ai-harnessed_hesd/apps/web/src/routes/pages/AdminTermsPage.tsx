import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { TermCreateForm } from "../../components/domain/TermCreateForm";
import { TermList } from "../../components/domain/TermList";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { fetchCurrentUser } from "../../lib/api/me-api";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import { isAcademicAdmin } from "../../lib/auth/role-guard";
import styles from "./AdminTermsPage.module.css";

export function AdminTermsPage() {
  const [showForm, setShowForm] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [authorized, setAuthorized] = useState<boolean | null>(null);

  useEffect(() => {
    void (async () => {
      if (!isStaffAuthenticated()) {
        setAuthorized(false);
        return;
      }
      const me = await fetchCurrentUser();
      setAuthorized(me.ok && isAcademicAdmin(me.roles));
    })();
  }, []);

  if (authorized === false) {
    if (!isStaffAuthenticated()) {
      return <Navigate to={buildStaffLoginRedirect("/admin/terms")} replace />;
    }
    return (
      <FeedbackAlert variant="danger" title="Không có quyền truy cập">
        Chỉ Quản trị học vụ mới có thể quản lý học kỳ.
      </FeedbackAlert>
    );
  }

  return (
    <div className={styles.content}>
      <FeedbackAlert variant="brand" title="Quản lý học kỳ">
        Tạo và quản lý học kỳ — bước đầu tiên trong thiết lập cấu trúc học thuật (FR-01).
      </FeedbackAlert>

      {showForm ? (
        <ContentSection title="Tạo học kỳ mới">
          <TermCreateForm
            onCancel={() => setShowForm(false)}
            onSuccess={() => {
              setRefreshToken((value) => value + 1);
              setShowForm(false);
            }}
          />
        </ContentSection>
      ) : null}

      <ContentSection title="Danh sách học kỳ">
        <TermList
          refreshToken={refreshToken}
          onCreateClick={() => setShowForm(true)}
        />
      </ContentSection>
    </div>
  );
}
