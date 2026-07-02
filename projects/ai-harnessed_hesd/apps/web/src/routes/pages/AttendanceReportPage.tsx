import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { AttendanceReportList } from "../../components/domain/AttendanceReportList";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import { fetchCurrentUser } from "../../lib/api/me-api";
import {
  DEFAULT_SECTION_LABEL,
  DEFAULT_TERM_LABEL,
  SEED_SECTION_ID,
  SEED_TERM_ID,
} from "../../lib/api/seed-fixtures";
import {
  canAccessInstitutionReport,
  canExecuteExport,
  isReadOnlyStaffRole,
} from "../../lib/auth/role-guard";
import { getAccessToken } from "../../lib/auth/session";
import { buildStaffLoginRedirect } from "../../lib/auth/staff-gate";
import styles from "./AttendanceReportPage.module.css";

export function AttendanceReportPage() {
  const [searchParams] = useSearchParams();
  const [roles, setRoles] = useState<string[] | null>(null);
  const [sectionOptions, setSectionOptions] = useState([
    { value: SEED_SECTION_ID, label: DEFAULT_SECTION_LABEL },
  ]);
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
      if (!canAccessInstitutionReport(me.roles)) {
        setAccessDenied(true);
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
    })();
  }, []);

  if (roles === null) {
    return (
      <ContentSection title="Báo cáo điểm danh" titleClassName={styles.title}>
        <AttendanceReportList
          authPending
          roles={[]}
          defaultTermId={SEED_TERM_ID}
          termOptions={[{ value: SEED_TERM_ID, label: DEFAULT_TERM_LABEL }]}
          sectionOptions={sectionOptions}
          canExport={false}
          readOnlyStaff={false}
        />
      </ContentSection>
    );
  }

  if (accessDenied || !canAccessInstitutionReport(roles)) {
    return (
      <ContentSection title="Báo cáo điểm danh" titleClassName={styles.title}>
        <FeedbackAlert variant="danger" title="Không có quyền truy cập">
          Bạn không có quyền xem báo cáo điểm danh toàn trường. Sinh viên vui lòng sử dụng{" "}
          <a href="/me/attendance">lịch sử điểm danh cá nhân</a>.
        </FeedbackAlert>
      </ContentSection>
    );
  }

  const tamperedSection = searchParams.get("classSectionId");
  const assignedSectionIds = sectionOptions.map((option) => option.value);
  const outOfScope =
    tamperedSection !== null &&
    tamperedSection.length > 0 &&
    !assignedSectionIds.includes(tamperedSection);

  return (
    <ContentSection title="Báo cáo điểm danh" titleClassName={styles.title}>
      {outOfScope ? (
        <FeedbackAlert variant="danger" title="Ngoài phạm vi được phép">
          Lớp học phần được chọn nằm ngoài phạm vi phân công của bạn. Không có dữ liệu được hiển
          thị.
        </FeedbackAlert>
      ) : (
        <AttendanceReportList
          roles={roles}
          defaultTermId={SEED_TERM_ID}
          termOptions={[{ value: SEED_TERM_ID, label: DEFAULT_TERM_LABEL }]}
          sectionOptions={sectionOptions}
          canExport={canExecuteExport(roles)}
          readOnlyStaff={isReadOnlyStaffRole(roles)}
        />
      )}
    </ContentSection>
  );
}

export function StudentAttendanceReportGuard() {
  if (!getAccessToken()) {
    return <Navigate to={buildStaffLoginRedirect("/reports/attendance")} replace />;
  }
  return <AttendanceReportPage />;
}
