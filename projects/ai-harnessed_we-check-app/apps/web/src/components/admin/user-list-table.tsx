import { Pencil, UserX } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Skeleton } from "@/components/ui/skeleton";
import { userCopy } from "@/lib/copy/user-labels";
import { roleLabels } from "@/lib/copy/status-labels";
import { cn } from "@/lib/cn";
import { updateUser, type UserDto } from "@/lib/users-api";

function UserActiveBadge({ active }: { active: boolean }) {
  return (
    <Badge
      variant="outline"
      className={cn(
        active
          ? "border-success-200 bg-success-50 text-success-700"
          : "border-border bg-surface text-text-secondary",
      )}
      data-testid={active ? "user-active-badge" : "user-inactive-badge"}
    >
      {active ? userCopy.activeBadge : userCopy.inactiveBadge}
    </Badge>
  );
}

function DeactivateConfirmDialog({
  user,
  onCancel,
  onConfirmed,
}: {
  user: UserDto;
  onCancel: () => void;
  onConfirmed: () => void;
}) {
  const [loading, setLoading] = useState(false);

  async function handleConfirm() {
    setLoading(true);
    const result = await updateUser(user.id, { active: false });
    setLoading(false);
    if (!result.ok) {
      toast.error(result.error.message ?? userCopy.loadError);
      return;
    }
    toast.success(userCopy.deactivateSuccess);
    onConfirmed();
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="deactivate-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      data-testid="deactivate-user-dialog"
    >
      <div className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg">
        <h2 id="deactivate-dialog-title" className="text-h2 font-semibold">
          {userCopy.deactivateConfirmTitle}
        </h2>
        <p className="mt-2 text-body text-text-secondary">
          {userCopy.deactivateConfirmDescription}
        </p>
        <p className="mt-2 text-small font-medium text-text-primary">
          {user.displayName} ({user.institutionalId})
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            {userCopy.cancelButton}
          </Button>
          <Button
            type="button"
            variant="danger"
            loading={loading}
            data-testid="confirm-dialog-accept"
            onClick={() => void handleConfirm()}
          >
            {userCopy.deactivateConfirmButton}
          </Button>
        </div>
      </div>
    </div>
  );
}

export interface UserListTableProps {
  users: UserDto[];
  loading?: boolean;
  onUserUpdated?: () => void;
}

/** FR-01 / AC-01 / NFR-11 — admin user directory table */
export function UserListTable({ users, loading, onUserUpdated }: UserListTableProps) {
  const [deactivateTarget, setDeactivateTarget] = useState<UserDto | null>(null);

  if (loading) {
    return (
      <div className="flex flex-col gap-2" data-testid="user-list-loading" aria-busy="true">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }

  return (
    <>
      <div className="overflow-x-auto rounded-md border border-border" data-testid="user-list-table">
        <table className="w-full min-w-[720px] text-left text-body">
          <thead className="border-b border-border bg-surface-raised">
            <tr>
              <th scope="col" className="px-4 py-3 font-medium text-text-secondary">
                {userCopy.colInstitutionalId}
              </th>
              <th scope="col" className="px-4 py-3 font-medium text-text-secondary">
                {userCopy.colDisplayName}
              </th>
              <th scope="col" className="px-4 py-3 font-medium text-text-secondary">
                {userCopy.colEmail}
              </th>
              <th scope="col" className="px-4 py-3 font-medium text-text-secondary">
                {userCopy.colRole}
              </th>
              <th scope="col" className="px-4 py-3 font-medium text-text-secondary">
                {userCopy.colActive}
              </th>
              <th scope="col" className="px-4 py-3 font-medium text-text-secondary">
                <span className="sr-only">{userCopy.colActions}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr
                key={user.id}
                className={cn(
                  "border-b border-border last:border-b-0",
                  !user.active && "bg-surface text-text-secondary",
                )}
                data-testid={`user-row-${user.institutionalId}`}
              >
                <td className="px-4 py-3 font-mono text-small">{user.institutionalId}</td>
                <td className="px-4 py-3">{user.displayName}</td>
                <td className="px-4 py-3">{user.email}</td>
                <td className="px-4 py-3">{roleLabels[user.role]}</td>
                <td className="px-4 py-3">
                  <UserActiveBadge active={user.active} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1">
                    <Link
                      to={`/admin/users/${user.id}`}
                      className="inline-flex min-h-touch min-w-touch items-center justify-center rounded-md text-text-primary transition-colors hover:bg-primary-50 focus-visible:outline-none"
                      aria-label={`${userCopy.editAction} ${user.displayName}`}
                      data-testid={`edit-user-${user.institutionalId}`}
                    >
                      <Pencil className="h-4 w-4" />
                    </Link>
                    {user.active ? (
                      <IconButton
                        aria-label={`${userCopy.deactivateAction} ${user.displayName}`}
                        data-testid={`deactivate-user-${user.institutionalId}`}
                        onClick={() => setDeactivateTarget(user)}
                      >
                        <UserX className="h-4 w-4" />
                      </IconButton>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {deactivateTarget ? (
        <DeactivateConfirmDialog
          user={deactivateTarget}
          onCancel={() => setDeactivateTarget(null)}
          onConfirmed={() => {
            setDeactivateTarget(null);
            onUserUpdated?.();
          }}
        />
      ) : null}
    </>
  );
}

export function UserListTableError({ onRetry }: { onRetry?: () => void }) {
  return (
    <Alert variant="danger" title={userCopy.loadError}>
      <p className="mb-3">{userCopy.loadErrorDetail}</p>
      {onRetry ? (
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          {userCopy.retry}
        </Button>
      ) : null}
    </Alert>
  );
}
