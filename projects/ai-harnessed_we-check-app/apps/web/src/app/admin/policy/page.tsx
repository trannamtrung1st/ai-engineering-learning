import { UserRole } from "@wecheck/domain";
import { AttendancePolicyForm } from "@/components/admin/attendance-policy-form";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { policyCopy } from "@/lib/copy/policy-labels";

/** FR-16 / AC-16 / BR-05 — admin attendance policy configuration */
export function AdminPolicyPage() {
  const authUser = useAuthUser();

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/sessions" />;
  }

  return (
    <div data-testid="admin-policy-page">
      <PageHeader
        title={policyCopy.pageTitle}
        description={policyCopy.pageDescription}
      />
      <AttendancePolicyForm />
    </div>
  );
}
