import { UserRole } from "@wecheck/domain";
import { ClassSubjectForm } from "@/components/admin/class-subject-form";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { classSubjectCopy } from "@/lib/copy/class-subject-labels";

/** FR-03 / AC-03d — manual class and subject reference creation */
export function CreateClassSubjectPage() {
  const authUser = useAuthUser();

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  return (
    <div data-testid="admin-classes-new-page">
      <PageHeader
        title={classSubjectCopy.pageTitle}
        description={classSubjectCopy.pageDescription}
        backTo="/admin/rosters"
      />
      <ClassSubjectForm />
    </div>
  );
}
