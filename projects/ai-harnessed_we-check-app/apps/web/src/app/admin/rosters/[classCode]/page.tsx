import { Users } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { useState } from "react";
import { ClassRosterTable } from "@/components/admin/class-roster-table";
import {
  RosterFilterBar,
  type RosterFilterSelection,
} from "@/components/admin/roster-filter-bar";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { rosterCopy } from "@/lib/copy/roster-labels";
import { canViewRoster } from "@/lib/roster-access";
import { fetchEnrollments, type EnrollmentDto } from "@/lib/roster-api";

/** FR-03 / AC-03 — class-scoped roster view at /admin/rosters/:classCode */
export function AdminClassRosterPage() {
  const { classCode } = useParams<{ classCode: string }>();
  const authUser = useAuthUser();
  const [selection, setSelection] = useState<RosterFilterSelection | null>(null);
  const [enrollments, setEnrollments] = useState<EnrollmentDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  if (!canViewRoster(authUser.role)) {
    return <ForbiddenPage homeTo="/sessions" />;
  }

  async function loadRoster(next: RosterFilterSelection) {
    setSelection(next);
    setLoading(true);
    setError(null);
    setLoaded(true);

    const result = await fetchEnrollments(next.classId, next.subjectId);
    setLoading(false);

    if (!result.ok) {
      if (result.status === 403) {
        setError(rosterCopy.accessDenied);
      } else {
        setError(result.error.message ?? rosterCopy.loadError);
      }
      setEnrollments([]);
      return;
    }

    setEnrollments(result.data.enrollments);
  }

  return (
    <div data-testid="admin-class-roster-page">
      <PageHeader
        title={`${rosterCopy.pageTitle} — ${classCode ?? ""}`}
        description={rosterCopy.pageDescription}
        actions={
          <Link
            to="/admin/rosters"
            className="inline-flex min-h-touch items-center justify-center rounded-md border border-border px-4 font-medium hover:bg-surface-raised"
          >
            {rosterCopy.backToRosters}
          </Link>
        }
      />

      <RosterFilterBar
        initialClassCode={classCode}
        autoApply
        onApply={(next) => void loadRoster(next)}
        disabled={loading}
      />

      {!loaded ? null : error ? (
        <Alert variant="danger" title={rosterCopy.loadError}>
          {error}
          <div className="mt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                if (selection) void loadRoster(selection);
              }}
            >
              {rosterCopy.retry}
            </Button>
          </div>
        </Alert>
      ) : loading ? (
        <ClassRosterTable enrollments={[]} loading />
      ) : selection && enrollments.length === 0 && !loading ? (
        <EmptyState
          icon={Users}
          title={rosterCopy.emptyTitle}
          description={rosterCopy.emptyDescription}
        />
      ) : (
        <ClassRosterTable enrollments={enrollments} />
      )}
    </div>
  );
}
