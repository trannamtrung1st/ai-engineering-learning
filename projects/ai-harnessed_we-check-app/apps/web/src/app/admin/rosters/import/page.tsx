import { Link } from "react-router-dom";
import { RosterImportPanel } from "@/components/admin/roster-import-panel";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { rosterCopy } from "@/lib/copy/roster-labels";
import { canImportRoster } from "@/lib/roster-access";

/** FR-03 / AC-03 — admin roster CSV import page */
export function RosterImportPage() {
  const authUser = useAuthUser();

  if (!canImportRoster(authUser.role)) {
    return <ForbiddenPage homeTo="/sessions" />;
  }

  return (
    <div data-testid="roster-import-page">
      <PageHeader
        title={rosterCopy.importPageTitle}
        description={rosterCopy.importPageDescription}
        actions={
          <Link
            to="/admin/rosters"
            className="inline-flex min-h-touch items-center justify-center rounded-md border border-border px-4 font-medium hover:bg-surface-raised"
          >
            {rosterCopy.backToRosters}
          </Link>
        }
      />
      <RosterImportPanel />
    </div>
  );
}
