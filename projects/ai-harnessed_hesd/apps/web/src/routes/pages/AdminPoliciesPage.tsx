import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { PolicyForm } from "../../components/domain/PolicyForm";
import { PolicyList } from "../../components/domain/PolicyList";
import { ContentSection } from "../../components/layout/ContentSection";
import { FeedbackAlert } from "../../components/ui/FeedbackAlert";
import type { PolicySummary } from "../../lib/api/policy-api";
import { fetchCurrentUser } from "../../lib/api/me-api";
import { buildStaffLoginRedirect, isStaffAuthenticated } from "../../lib/auth/staff-gate";
import { isAcademicAdmin } from "../../lib/auth/role-guard";
import styles from "./AdminPoliciesPage.module.css";

type FormMode = "hidden" | "create" | "edit";

export function AdminPoliciesPage() {
  const [formMode, setFormMode] = useState<FormMode>("hidden");
  const [editingPolicy, setEditingPolicy] = useState<PolicySummary | undefined>();
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
      return <Navigate to={buildStaffLoginRedirect("/admin/policies")} replace />;
    }
    return (
      <FeedbackAlert variant="danger" title="Không có quyền truy cập">
        Chỉ Quản trị học vụ mới có thể cấu hình chính sách điểm danh.
      </FeedbackAlert>
    );
  }

  return (
    <div className={styles.content}>
      <FeedbackAlert variant="brand" title="Chính sách điểm danh (PG-12)">
        Cấu hình cửa sổ điểm danh, GPS và quy tắc chỉnh sửa theo phạm vi — xem trước hiệu lực BR-20
        trước khi lưu (FR-24, FR-25).
      </FeedbackAlert>

      {formMode !== "hidden" ? (
        <ContentSection title={formMode === "edit" ? "Sửa chính sách" : "Tạo chính sách mới"}>
          <PolicyForm
            mode={formMode === "edit" ? "edit" : "create"}
            initialPolicy={editingPolicy}
            onCancel={() => {
              setFormMode("hidden");
              setEditingPolicy(undefined);
            }}
            onSuccess={() => {
              setRefreshToken((value) => value + 1);
              setFormMode("hidden");
              setEditingPolicy(undefined);
            }}
          />
        </ContentSection>
      ) : null}

      <ContentSection title="Danh sách chính sách">
        <PolicyList
          refreshToken={refreshToken}
          onCreateClick={() => {
            setEditingPolicy(undefined);
            setFormMode("create");
          }}
          onEditClick={(policy) => {
            setEditingPolicy(policy);
            setFormMode("edit");
          }}
        />
      </ContentSection>
    </div>
  );
}
