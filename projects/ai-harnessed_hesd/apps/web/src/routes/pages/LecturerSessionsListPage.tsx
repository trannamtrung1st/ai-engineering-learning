import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { LecturerSessionList } from "../../components/domain/LecturerSessionList";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { fetchCurrentUser } from "../../lib/api/me-api";
import {
  DEFAULT_SECTION_LABEL,
  SEED_SECTION_ID,
} from "../../lib/api/seed-fixtures";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import { canAccessSessionControl } from "../../lib/auth/role-guard";
import styles from "./LecturerSessionsListPage.module.css";

export function LecturerSessionsListPage() {
  const [ready, setReady] = useState(false);
  const [accessDenied, setAccessDenied] = useState(false);
  const [sectionOptions, setSectionOptions] = useState([
    { value: SEED_SECTION_ID, label: DEFAULT_SECTION_LABEL },
  ]);

  useEffect(() => {
    void (async () => {
      const me = await fetchCurrentUser();
      if (!me.ok || !canAccessSessionControl(me.roles)) {
        setAccessDenied(true);
        setReady(true);
        return;
      }
      if (me.classSectionIds.length > 0) {
        setSectionOptions(
          me.classSectionIds.map((id) => ({
            value: id,
            label: id === SEED_SECTION_ID ? DEFAULT_SECTION_LABEL : id.slice(0, 8),
          })),
        );
      }
      setReady(true);
    })();
  }, []);

  if (!isStaffAuthenticated()) {
    return <Navigate to={buildStaffLoginRedirect("/lecturer/sessions")} replace />;
  }

  if (ready && accessDenied) {
    return (
      <ContentSection title="Danh sách buổi học" titleClassName={styles.sectionTitle}>
        <FeedbackAlert variant="danger" title="Không có quyền truy cập">
          Sinh viên không thể mở không gian điều khiển buổi học. Vui lòng xem{" "}
          <a href="/me/attendance">lịch sử điểm danh cá nhân</a>.
        </FeedbackAlert>
      </ContentSection>
    );
  }

  return (
    <div className={styles.content}>
      <FeedbackAlert variant="brand" title="Buổi học được phân công">
        Chỉ hiển thị các lớp học phần bạn được phân công giảng dạy. Mở buổi học để bắt đầu
        điểm danh QR.
      </FeedbackAlert>

      <ContentSection title="Danh sách buổi học" titleClassName={styles.sectionTitle}>
        {ready ? (
          <LecturerSessionList sectionOptions={sectionOptions} />
        ) : (
          <div className={styles.loading} aria-busy="true" />
        )}
      </ContentSection>
    </div>
  );
}
