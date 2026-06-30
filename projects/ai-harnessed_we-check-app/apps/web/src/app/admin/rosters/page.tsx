import { Plus, Upload, Users } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
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
import { canImportRoster, canViewRoster } from "@/lib/roster-access";
import { fetchEnrollments, type EnrollmentDto } from "@/lib/roster-api";

/** FR-03 / AC-03 — admin class roster listing with class-subject filter */
export function AdminRostersPage() {
  const authUser = useAuthUser();
  const [selection, setSelection] = useState<RosterFilterSelection | null>(null);
  const [enrollments, setEnrollments] = useState<EnrollmentDto[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);

  if (!canViewRoster(authUser.role)) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  const showImport = canImportRoster(authUser.role);

  async function handleApply(next: RosterFilterSelection) {
    setSelection(next);
    setApplied(true);
    setLoading(true);
    setError(null);

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
    <div data-testid="admin-rosters-page">
      <PageHeader
        title={rosterCopy.pageTitle}
        description={rosterCopy.pageDescription}
        actions={
          showImport ? (
            <div className="flex flex-wrap gap-2">
              <Link
                to="/admin/classes/new"
                className="inline-flex min-h-touch items-center justify-center gap-2 rounded-md border border-border bg-surface-raised px-4 font-medium text-text-primary hover:bg-surface"
                data-testid="class-subject-create-link"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Thêm lớp/môn
              </Link>
              <Link
                to="/admin/rosters/import"
                className="inline-flex min-h-touch items-center justify-center gap-2 rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
                data-testid="roster-import-link"
              >
                <Upload className="h-4 w-4" aria-hidden="true" />
                {rosterCopy.importButton}
              </Link>
            </div>
          ) : undefined
        }
      />

      <RosterFilterBar onApply={(next) => void handleApply(next)} disabled={loading} />

      {!applied ? (
        <p className="text-body text-text-secondary">{rosterCopy.filterPrompt}</p>
      ) : error ? (
        <Alert variant="danger" title={rosterCopy.loadError}>
          {error}
          <div className="mt-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                if (selection) void handleApply(selection);
              }}
            >
              {rosterCopy.retry}
            </Button>
          </div>
        </Alert>
      ) : loading ? (
        <ClassRosterTable enrollments={[]} loading />
      ) : enrollments.length === 0 ? (
        <EmptyState
          icon={Users}
          title={rosterCopy.emptyTitle}
          description={rosterCopy.emptyDescription}
          action={
            showImport ? (
              <Link
                to="/admin/rosters/import"
                className="inline-flex min-h-touch items-center justify-center rounded-md bg-primary-600 px-4 font-medium text-primary-foreground hover:bg-primary-700"
              >
                {rosterCopy.importButton}
              </Link>
            ) : undefined
          }
        />
      ) : (
        <>
          {selection ? (
            <p className="mb-3 text-small text-text-secondary" data-testid="roster-scope-label">
              {selection.classCode} / {selection.subjectCode} — {enrollments.length} sinh viên
            </p>
          ) : null}
          <ClassRosterTable enrollments={enrollments} />
        </>
      )}
    </div>
  );
}
