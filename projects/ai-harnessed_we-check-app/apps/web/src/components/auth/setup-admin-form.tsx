import { useState } from "react";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createFirstAdmin } from "@/lib/setup-api";
import { setupCopy } from "@/lib/copy/setup-labels";
import {
  validateSetupForm,
  type SetupFormValues,
} from "@/lib/setup-form-validation";
import { mapApiDetailsToFieldErrors } from "@/lib/users-api";

const emptyValues: SetupFormValues = {
  institutionalId: "",
  displayName: "",
  email: "",
  password: "",
};

/** FR-17 / AC-17 / NFR-16 — first TrainingOfficeAdmin bootstrap form */
export function SetupAdminForm() {
  const [values, setValues] = useState<SetupFormValues>(emptyValues);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);

    const clientErrors = validateSetupForm(values);
    if (Object.keys(clientErrors).length > 0) {
      setFieldErrors(clientErrors);
      return;
    }

    setFieldErrors({});
    setSubmitting(true);

    try {
      const result = await createFirstAdmin({
        institutionalId: values.institutionalId.trim(),
        displayName: values.displayName.trim(),
        email: values.email.trim(),
        password: values.password,
      });

      if (result.ok) {
        toast.success(setupCopy.successToast);
        window.location.href = "/admin";
        return;
      }

      if (result.status === 422 && result.error.details?.length) {
        setFieldErrors(mapApiDetailsToFieldErrors(result.error.details));
        return;
      }

      if (result.error.errorCode === "SetupAlreadyComplete") {
        setFormError(setupCopy.setupClosed);
        return;
      }

      setFormError(result.error.message ?? setupCopy.genericError);
    } catch {
      setFormError(setupCopy.genericError);
    } finally {
      setSubmitting(false);
    }
  }

  function updateField<K extends keyof SetupFormValues>(field: K, value: SetupFormValues[K]) {
    setValues((prev) => ({ ...prev, [field]: value }));
    if (fieldErrors[field]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="flex flex-col gap-4"
      data-testid="setup-admin-form"
    >
      <div>
        <h1 className="text-h1 font-semibold">{setupCopy.pageTitle}</h1>
        <p className="mt-1 text-body text-text-secondary">{setupCopy.pageDescription}</p>
      </div>

      {formError ? (
        <Alert variant="danger" data-testid="setup-form-error">
          {formError}
        </Alert>
      ) : null}

      <div className="flex flex-col gap-2">
        <Label htmlFor="setup-institutional-id">{setupCopy.fieldInstitutionalId}</Label>
        <Input
          id="setup-institutional-id"
          autoComplete="username"
          value={values.institutionalId}
          onChange={(e) => updateField("institutionalId", e.target.value)}
          aria-invalid={Boolean(fieldErrors.institutionalId)}
          aria-describedby={
            fieldErrors.institutionalId ? "setup-institutional-id-error" : undefined
          }
          required
        />
        {fieldErrors.institutionalId ? (
          <p id="setup-institutional-id-error" className="text-small text-danger" role="alert">
            {fieldErrors.institutionalId}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="setup-display-name">{setupCopy.fieldDisplayName}</Label>
        <Input
          id="setup-display-name"
          autoComplete="name"
          value={values.displayName}
          onChange={(e) => updateField("displayName", e.target.value)}
          aria-invalid={Boolean(fieldErrors.displayName)}
          aria-describedby={fieldErrors.displayName ? "setup-display-name-error" : undefined}
          required
        />
        {fieldErrors.displayName ? (
          <p id="setup-display-name-error" className="text-small text-danger" role="alert">
            {fieldErrors.displayName}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="setup-email">{setupCopy.fieldEmail}</Label>
        <Input
          id="setup-email"
          type="email"
          autoComplete="email"
          value={values.email}
          onChange={(e) => updateField("email", e.target.value)}
          aria-invalid={Boolean(fieldErrors.email)}
          aria-describedby={fieldErrors.email ? "setup-email-error" : undefined}
          required
        />
        {fieldErrors.email ? (
          <p id="setup-email-error" className="text-small text-danger" role="alert">
            {fieldErrors.email}
          </p>
        ) : null}
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="setup-password">{setupCopy.fieldPassword}</Label>
        <Input
          id="setup-password"
          type="password"
          autoComplete="new-password"
          value={values.password}
          onChange={(e) => updateField("password", e.target.value)}
          aria-invalid={Boolean(fieldErrors.password)}
          aria-describedby={fieldErrors.password ? "setup-password-error" : undefined}
          required
        />
        {fieldErrors.password ? (
          <p id="setup-password-error" className="text-small text-danger" role="alert">
            {fieldErrors.password}
          </p>
        ) : null}
      </div>

      <Button type="submit" loading={submitting} className="w-full" aria-busy={submitting}>
        {setupCopy.submitLabel}
      </Button>
    </form>
  );
}
