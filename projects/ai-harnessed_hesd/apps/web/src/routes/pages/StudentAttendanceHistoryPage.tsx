import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { AttendanceHistoryList } from "../../components/domain/AttendanceHistoryList";
import { MobileFlowContainer } from "../../components/layout/MobileFlowContainer";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import {
  buildSectionFilterOptions,
  fetchAttendanceHistory,
} from "../../lib/api/attendance-history-api";
import { fetchCurrentUser } from "../../lib/api/me-api";
import {
  DEFAULT_SECTION_LABEL,
  DEFAULT_TERM_LABEL,
  SEED_SECTION_ID,
  SEED_TERM_ID,
} from "../../lib/api/seed-fixtures";
import {
  buildLoginRedirect,
  isStudentAuthenticated,
} from "../../lib/auth/auth-gate";
import { DEFAULT_LISTING_QUERY } from "../../lib/listing/query-state";
import styles from "./StudentAttendanceHistoryPage.module.css";

export function StudentAttendanceHistoryPage() {
  const [ready, setReady] = useState(false);
  const [sectionOptions, setSectionOptions] = useState<
    { value: string; label: string }[]
  >([]);

  useEffect(() => {
    void (async () => {
      const me = await fetchCurrentUser();
      const sectionIds = me.ok ? me.classSectionIds : [];
      const history = await fetchAttendanceHistory({
        ...DEFAULT_LISTING_QUERY,
        termId: SEED_TERM_ID,
        pageSize: 100,
      });
      const rows = history.ok ? history.rows : [];
      setSectionOptions(
        buildSectionFilterOptions(sectionIds, rows, SEED_SECTION_ID, DEFAULT_SECTION_LABEL),
      );
      setReady(true);
    })();
  }, []);

  if (!isStudentAuthenticated()) {
    const gate = buildLoginRedirect("/me/attendance");
    return <Navigate to={gate.redirectTo} replace />;
  }

  return (
    <MobileFlowContainer
      title="Lịch sử điểm danh"
      subtitle="Chỉ hiển thị bản ghi của bạn"
    >
      <FeedbackAlert variant="brand" title="Phạm vi cá nhân">
        Dữ liệu được giới hạn trong các lớp bạn đã ghi danh. Không có chức năng xuất báo cáo
        toàn trường.
      </FeedbackAlert>

      <div className={styles.content}>
        {ready ? (
          <AttendanceHistoryList
            defaultTermId={SEED_TERM_ID}
            termOptions={[{ value: SEED_TERM_ID, label: DEFAULT_TERM_LABEL }]}
            sectionOptions={sectionOptions}
          />
        ) : (
          <div className={styles.loading} aria-busy="true" />
        )}
      </div>
    </MobileFlowContainer>
  );
}
