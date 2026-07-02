import { UserRole } from "@wecheck/domain";
import { Link } from "react-router-dom";
import { UserImportForm } from "@/components/admin/user-import-form";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { userImportCopy } from "@/lib/copy/user-import-labels";

/** FR-01 / AC-01 — admin user CSV import page */
export function UserImportPage() {
  const authUser = useAuthUser();

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  return (
    <div data-testid="user-import-page">
      <PageHeader
        title={userImportCopy.pageTitle}
        description={userImportCopy.pageDescription}
        actions={
          <Link
            to="/admin/users"
            className="inline-flex min-h-touch items-center justify-center rounded-md border border-border px-4 font-medium hover:bg-surface-raised"
          >
            {userImportCopy.backToUsers}
          </Link>
        }
      />
      <UserImportForm />
    </div>
  );
}
