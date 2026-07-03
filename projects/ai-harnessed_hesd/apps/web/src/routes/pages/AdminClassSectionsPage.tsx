import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { ClassSectionCreateForm } from "../../components/domain/ClassSectionCreateForm";
import { ClassSectionList } from "../../components/domain/ClassSectionList";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { fetchTerms } from "../../lib/api/academic-api";
import { fetchCurrentUser } from "../../lib/api/me-api";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import { isAcademicAdmin } from "../../lib/auth/role-guard";
import styles from "./AdminClassSectionsPage.module.css";

export function AdminClassSectionsPage() {
  const [showForm, setShowForm] = useState(false);
  const [refreshToken, setRefreshToken] = useState(0);
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [termOptions, setTermOptions] = useState<{ value: string; label: string }[]>([]);
  const [lastSessionCount, setLastSessionCount] = useState<number | null>(null);

  useEffect(() => {
    void (async () => {
      if (!isStaffAuthenticated()) {
        setAuthorized(false);
        return;
      }
      const me = await fetchCurrentUser();
      setAuthorized(me.ok && isAcademicAdmin(me.roles));

      const terms = await fetchTerms({ page: 1, pageSize: 100 });
      if (terms.ok) {
        setTermOptions(
          terms.items.map((term) => ({
            value: term.id,
            label: `${term.code} — ${term.name}`,
          })),
        );
      }
    })();
  }, [refreshToken]);

  if (authorized === false) {
    if (!isStaffAuthenticated()) {
      return <Navigate to={buildStaffLoginRedirect("/admin/class-sections")} replace />;
    }
    return (
      <FeedbackAlert variant="danger" title="Không có quyền truy cập">
        Chỉ Quản trị học vụ mới có thể quản lý lớp học phần.
      </FeedbackAlert>
    );
  }

  return (
    <div className={styles.content}>
      <FeedbackAlert variant="brand" title="Quản lý lớp học phần">
        Tạo lớp học phần với lịch mẫu để sinh buổi học Scheduled (FR-03, FR-06).
      </FeedbackAlert>

      {lastSessionCount != null ? (
        <FeedbackAlert variant="success" title="Buổi học đã được tạo">
          Đã sinh {lastSessionCount} buổi học ở trạng thái Scheduled từ lịch mẫu.
        </FeedbackAlert>
      ) : null}

      {showForm ? (
        <ContentSection title="Tạo lớp học phần">
          <ClassSectionCreateForm
            onCancel={() => setShowForm(false)}
            onSuccess={({ generatedSessionCount }) => {
              setRefreshToken((value) => value + 1);
              setShowForm(false);
              if (generatedSessionCount != null) {
                setLastSessionCount(generatedSessionCount);
              }
            }}
          />
        </ContentSection>
      ) : null}

      <ContentSection title="Danh sách lớp học phần">
        <ClassSectionList
          termOptions={termOptions}
          refreshToken={refreshToken}
          onCreateClick={() => setShowForm(true)}
        />
      </ContentSection>
    </div>
  );
}
