import { useEffect, useState } from "react";
import { Navigate, useParams } from "react-router-dom";
import { EnrollmentImportPanel } from "../../components/domain/EnrollmentImportPanel";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { fetchClassSections } from "../../lib/api/academic-api";
import { DEFAULT_SECTION_LABEL, SEED_SECTION_ID } from "../../lib/api/seed-fixtures";
import { fetchCurrentUser } from "../../lib/api/me-api";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import { isAcademicAdmin } from "../../lib/auth/role-guard";
import styles from "./AdminEnrollmentsPage.module.css";

export function AdminEnrollmentsPage() {
  const { sectionId = "" } = useParams();
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [sectionLabel, setSectionLabel] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      if (!isStaffAuthenticated()) {
        setAuthorized(false);
        return;
      }
      const me = await fetchCurrentUser();
      setAuthorized(me.ok && isAcademicAdmin(me.roles));

      if (sectionId) {
        const sections = await fetchClassSections({ page: 1, pageSize: 100 });
        if (sections.ok) {
          const match = sections.items.find((item) => item.id === sectionId);
          setSectionLabel(
            match?.sectionCode ??
              (sectionId === SEED_SECTION_ID ? DEFAULT_SECTION_LABEL : sectionId.slice(0, 8)),
          );
        }
      }
    })();
  }, [sectionId]);

  if (!sectionId) {
    return (
      <FeedbackAlert variant="danger" title="Thiếu mã lớp">
        Không tìm thấy lớp học phần.
      </FeedbackAlert>
    );
  }

  if (authorized === false) {
    if (!isStaffAuthenticated()) {
      return <Navigate to={buildStaffLoginRedirect(`/admin/class-sections/${sectionId}/enrollments`)} replace />;
    }
    return (
      <FeedbackAlert variant="danger" title="Không có quyền truy cập">
        Chỉ Quản trị học vụ mới có thể nhập danh sách đăng ký.
      </FeedbackAlert>
    );
  }

  return (
    <div className={styles.content}>
      <ContentSection title="Nhập đăng ký lớp học phần">
        <EnrollmentImportPanel classSectionId={sectionId} sectionLabel={sectionLabel ?? undefined} />
      </ContentSection>
    </div>
  );
}
