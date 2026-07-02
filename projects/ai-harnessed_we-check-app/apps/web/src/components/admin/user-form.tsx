import { UserRole, type UserRole as UserRoleType } from "@wecheck/domain";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { userCopy } from "@/lib/copy/user-labels";
import { roleLabels } from "@/lib/copy/status-labels";
import {
  validateUserForm,
  type UserFormValues,
} from "@/lib/user-form-validation";
import {
  checkUserFieldDuplicate,
  createUser,
  mapApiDetailsToFieldErrors,
  updateUser,
  type UserDto,
} from "@/lib/users-api";

const ROLE_OPTIONS: UserRoleType[] = [
  UserRole.Student,
  UserRole.Instructor,
  UserRole.TrainingOfficeAdmin,
];

const emptyValues: UserFormValues = {
  institutionalId: "",
  displayName: "",
  email: "",
  password: "",
  role: UserRole.Student,
};

function AdminRoleConfirmDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-role-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      data-testid="admin-role-confirm-dialog"
    >
      <div className="w-full max-w-md rounded-md bg-surface-raised p-6 shadow-lg">
        <h2 id="admin-role-dialog-title" className="text-h2 font-semibold">
          {userCopy.adminRoleConfirmTitle}
        </h2>
        <p className="mt-2 text-body text-text-secondary">
          {userCopy.adminRoleConfirmDescription}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel}>
            {userCopy.cancelButton}
          </Button>
          <Button
            type="button"
            data-testid="confirm-dialog-accept"
            onClick={onConfirm}
          >
            {userCopy.adminRoleConfirmButton}
          </Button>
        </div>
      </div>
    </div>
  );
}

export interface UserFormProps {
  mode: "create" | "edit";
  user?: UserDto;
  onSaved?: (user: UserDto) => void;
}

/** FR-01 / AC-01 / NFR-11 — provision and edit user accounts */
export function UserForm({ mode, user, onSaved }: UserFormProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<UserFormValues>(() =>
    user
      ? {
          institutionalId: user.institutionalId,
          displayName: user.displayName,
          email: user.email,
          password: "",
          role: user.role,
        }
      : emptyValues,
  );
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [showAdminConfirm, setShowAdminConfirm] = useState(false);
  const [pendingSubmit, setPendingSubmit] = useState(false);
  const blurTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    if (!user) return;
    setValues({
      institutionalId: user.institutionalId,
      displayName: user.displayName,
      email: user.email,
      password: "",
      role: user.role,
    });
  }, [user]);

  useEffect(() => {
    return () => {
      for (const timer of Object.values(blurTimers.current)) {
        clearTimeout(timer);
      }
    };
  }, []);

  function scheduleAsyncCheck(field: "institutionalId" | "email", value: string) {
    if (blurTimers.current[field]) {
      clearTimeout(blurTimers.current[field]);
    }
    blurTimers.current[field] = setTimeout(() => {
      void (async () => {
        const message = await checkUserFieldDuplicate(field, value, user?.id);
        if (!message) return;
        setFieldErrors((prev) => ({ ...prev, [field]: message }));
      })();
    }, 300);
  }

  function handleBlur(field: "institutionalId" | "email") {
    const value = values[field];
    if (!value.trim()) return;
    scheduleAsyncCheck(field, value);
  }

  async function submitForm(skipAdminConfirm = false) {
    const errors = validateUserForm(values, {
      mode,
      requirePassword: mode === "create",
    });
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    if (
      !skipAdminConfirm &&
      values.role === UserRole.TrainingOfficeAdmin &&
      user?.role !== UserRole.TrainingOfficeAdmin
    ) {
      setShowAdminConfirm(true);
      setPendingSubmit(true);
      return;
    }

    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    if (mode === "create") {
      const result = await createUser({
        institutionalId: values.institutionalId.trim(),
        displayName: values.displayName.trim(),
        email: values.email.trim().toLowerCase(),
        password: values.password,
        role: values.role as UserRoleType,
        active: true,
      });
      setSubmitting(false);
      if (!result.ok) {
        if (result.status === 403) {
          setFormError(result.error.message ?? userCopy.accessDenied);
          return;
        }
        const apiFieldErrors = mapApiDetailsToFieldErrors(result.error.details);
        if (Object.keys(apiFieldErrors).length > 0) {
          setFieldErrors(apiFieldErrors);
          return;
        }
        setFormError(result.error.message ?? userCopy.loadError);
        return;
      }
      toast.success(userCopy.createSuccess);
      onSaved?.(result.data);
      navigate("/admin/users");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
      return;
    }

    if (!user) return;

    const payload: Parameters<typeof updateUser>[1] = {
      institutionalId: values.institutionalId.trim(),
      displayName: values.displayName.trim(),
      email: values.email.trim().toLowerCase(),
      role: values.role as UserRoleType,
    };
    if (values.password) {
      payload.password = values.password;
    }

    const result = await updateUser(user.id, payload);
    setSubmitting(false);
    if (!result.ok) {
      if (result.status === 403) {
        setFormError(result.error.message ?? userCopy.accessDenied);
        return;
      }
      const apiFieldErrors = mapApiDetailsToFieldErrors(result.error.details);
      if (Object.keys(apiFieldErrors).length > 0) {
        setFieldErrors(apiFieldErrors);
        return;
      }
      setFormError(result.error.message ?? userCopy.loadError);
      return;
    }
    toast.success(userCopy.saveSuccess);
    onSaved?.(result.data);
    navigate("/admin/users");
    void queryClient.invalidateQueries({ queryKey: ["users"] });
  }

  return (
    <>
      <form
        className="mx-auto max-w-xl flex flex-col gap-4"
        data-testid="user-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submitForm();
        }}
        aria-busy={submitting}
      >
        {formError ? (
          <Alert variant="danger" title="Không thể lưu">
            {formError}
          </Alert>
        ) : null}

        <div>
          <Label htmlFor="user-institutional-id">
            {userCopy.fieldInstitutionalId} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="user-institutional-id"
            value={values.institutionalId}
            disabled={mode === "edit"}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.institutionalId)}
            aria-describedby={
              fieldErrors.institutionalId ? "user-institutional-id-error" : undefined
            }
            onChange={(e) =>
              setValues((v) => ({ ...v, institutionalId: e.target.value }))
            }
            onBlur={() => handleBlur("institutionalId")}
          />
          {fieldErrors.institutionalId ? (
            <p
              id="user-institutional-id-error"
              className="mt-1 text-small text-danger-600"
              role="alert"
            >
              {fieldErrors.institutionalId}
            </p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="user-display-name">
            {userCopy.fieldDisplayName} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="user-display-name"
            value={values.displayName}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.displayName)}
            onChange={(e) => setValues((v) => ({ ...v, displayName: e.target.value }))}
          />
          {fieldErrors.displayName ? (
            <p className="mt-1 text-small text-danger-600" role="alert">
              {fieldErrors.displayName}
            </p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="user-email">
            {userCopy.fieldEmail} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="user-email"
            type="email"
            autoComplete="email"
            value={values.email}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.email)}
            onChange={(e) => setValues((v) => ({ ...v, email: e.target.value }))}
            onBlur={() => handleBlur("email")}
          />
          {fieldErrors.email ? (
            <p className="mt-1 text-small text-danger-600" role="alert">
              {fieldErrors.email}
            </p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="user-password">
            {userCopy.fieldPassword}
            {mode === "create" ? <span aria-hidden="true"> *</span> : null}
          </Label>
          <Input
            id="user-password"
            type="password"
            autoComplete={mode === "create" ? "new-password" : "off"}
            value={values.password}
            aria-required={mode === "create"}
            aria-invalid={Boolean(fieldErrors.password)}
            onChange={(e) => setValues((v) => ({ ...v, password: e.target.value }))}
          />
          <p className="mt-1 text-small text-text-secondary">{userCopy.passwordHint}</p>
          {fieldErrors.password ? (
            <p className="mt-1 text-small text-danger-600" role="alert">
              {fieldErrors.password}
            </p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="user-role">
            {userCopy.fieldRole} <span aria-hidden="true">*</span>
          </Label>
          <select
            id="user-role"
            className="mt-1 flex min-h-touch w-full rounded-md border border-border bg-surface-raised px-3 text-body"
            value={values.role}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.role)}
            onChange={(e) =>
              setValues((v) => ({ ...v, role: e.target.value as UserRoleType }))
            }
          >
            {ROLE_OPTIONS.map((role) => (
              <option key={role} value={role}>
                {roleLabels[role]}
              </option>
            ))}
          </select>
          {fieldErrors.role ? (
            <p className="mt-1 text-small text-danger-600" role="alert">
              {fieldErrors.role}
            </p>
          ) : null}
        </div>

        {mode === "edit" && user ? (
          <p className="text-body text-text-secondary">
            {user.active ? userCopy.activeBadge : userCopy.inactiveBadge}
            {!user.active ? null : (
              <span className="ml-2 text-small">
                — Vô hiệu hóa từ danh sách người dùng.
              </span>
            )}
          </p>
        ) : null}

        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => navigate("/admin/users")}
          >
            {userCopy.cancelButton}
          </Button>
          <Button type="submit" loading={submitting} data-testid="user-form-submit">
            {userCopy.saveButton}
          </Button>
        </div>
      </form>

      {showAdminConfirm ? (
        <AdminRoleConfirmDialog
          onCancel={() => {
            setShowAdminConfirm(false);
            setPendingSubmit(false);
          }}
          onConfirm={() => {
            setShowAdminConfirm(false);
            if (pendingSubmit) {
              setPendingSubmit(false);
              void submitForm(true);
            }
          }}
        />
      ) : null}
    </>
  );
}
