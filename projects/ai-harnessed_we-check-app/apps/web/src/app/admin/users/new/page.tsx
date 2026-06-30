import { UserRole } from "@wecheck/domain";
import { UserForm } from "@/components/admin/user-form";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { userCopy } from "@/lib/copy/user-labels";

/** FR-01 / AC-01 — create user account */
export function CreateUserPage() {
  const authUser = useAuthUser();

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  return (
    <div data-testid="admin-users-create-page">
      <PageHeader
        title={userCopy.createTitle}
        description={userCopy.pageDescription}
        backTo="/admin/users"
      />
      <UserForm mode="create" />
    </div>
  );
}
