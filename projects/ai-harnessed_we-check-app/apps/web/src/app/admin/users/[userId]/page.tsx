import { UserRole } from "@wecheck/domain";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { UserForm } from "@/components/admin/user-form";
import { useAuthUser } from "@/components/auth/require-auth";
import { ForbiddenPage } from "@/components/layout/forbidden-page";
import { PageHeader } from "@/components/layout/page-header";
import { Alert } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { userCopy } from "@/lib/copy/user-labels";
import { fetchUserById, type UserDto } from "@/lib/users-api";

/** FR-01 / AC-01 — edit user account */
export function EditUserPage() {
  const authUser = useAuthUser();
  const { userId } = useParams<{ userId: string }>();
  const [user, setUser] = useState<UserDto | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!userId) {
      setNotFound(true);
      setLoading(false);
      return;
    }

    let cancelled = false;
    void (async () => {
      const result = await fetchUserById(userId);
      if (cancelled) return;
      if (!result) {
        setNotFound(true);
      } else {
        setUser(result);
      }
      setLoading(false);
    })();

    return () => {
      cancelled = true;
    };
  }, [userId]);

  if (authUser.role !== UserRole.TrainingOfficeAdmin) {
    return <ForbiddenPage homeTo="/check-in" />;
  }

  if (loading) {
    return (
      <div className="flex justify-center py-12" data-testid="admin-users-edit-loading">
        <Spinner />
      </div>
    );
  }

  if (notFound || !user) {
    return (
      <div data-testid="admin-users-edit-not-found">
        <PageHeader title={userCopy.userNotFound} backTo="/admin/users" />
        <Alert variant="danger">{userCopy.userNotFound}</Alert>
      </div>
    );
  }

  return (
    <div data-testid="admin-users-edit-page">
      <PageHeader
        title={userCopy.editTitle}
        description={`${user.displayName} (${user.institutionalId})`}
        backTo="/admin/users"
      />
      <UserForm mode="edit" user={user} />
    </div>
  );
}
