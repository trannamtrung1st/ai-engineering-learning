import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  normalizeReferenceCode,
  validateClassSubjectForm,
  type ClassSubjectFormValues,
} from "@/lib/class-subject-form-validation";
import { classSubjectCopy } from "@/lib/copy/class-subject-labels";
import {
  createClass,
  createSubject,
  mapReferenceApiErrorToFieldErrors,
} from "@/lib/reference-api";

const emptyValues: ClassSubjectFormValues = {
  classCode: "",
  className: "",
  subjectCode: "",
  subjectName: "",
};

/** FR-03 / AC-03d / AC-03e — manual class and subject reference creation */
export function ClassSubjectForm() {
  const navigate = useNavigate();
  const [values, setValues] = useState<ClassSubjectFormValues>(emptyValues);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submitForm() {
    const normalized: ClassSubjectFormValues = {
      classCode: normalizeReferenceCode(values.classCode),
      className: values.className.trim(),
      subjectCode: normalizeReferenceCode(values.subjectCode),
      subjectName: values.subjectName.trim(),
    };

    const errors = validateClassSubjectForm(normalized);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    setSubmitting(true);
    setFormError(null);
    setFieldErrors({});

    const classResult = await createClass({
      code: normalized.classCode,
      name: normalized.className,
    });

    if (!classResult.ok) {
      setSubmitting(false);
      if (classResult.status === 403) {
        setFormError(classResult.error.message ?? classSubjectCopy.accessDenied);
        return;
      }
      const apiFieldErrors = mapReferenceApiErrorToFieldErrors(classResult.error);
      if (Object.keys(apiFieldErrors).length > 0) {
        setFieldErrors(apiFieldErrors);
        return;
      }
      setFormError(classResult.error.message ?? classSubjectCopy.loadError);
      return;
    }

    const subjectResult = await createSubject({
      code: normalized.subjectCode,
      name: normalized.subjectName,
    });

    setSubmitting(false);

    if (!subjectResult.ok) {
      if (subjectResult.status === 403) {
        setFormError(subjectResult.error.message ?? classSubjectCopy.accessDenied);
        return;
      }
      const apiFieldErrors = mapReferenceApiErrorToFieldErrors(subjectResult.error);
      if (Object.keys(apiFieldErrors).length > 0) {
        setFieldErrors(apiFieldErrors);
        return;
      }
      setFormError(subjectResult.error.message ?? classSubjectCopy.loadError);
      return;
    }

    toast.success(classSubjectCopy.createSuccess);
    navigate("/admin/rosters");
  }

  return (
    <form
      className="mx-auto max-w-xl flex flex-col gap-6"
      data-testid="class-subject-form"
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

      <fieldset className="flex flex-col gap-4 rounded-md border border-border bg-surface-raised p-4">
        <legend className="px-1 text-h2 font-semibold text-primary-700">
          {classSubjectCopy.sectionClass}
        </legend>

        <div>
          <Label htmlFor="class-code">
            {classSubjectCopy.fieldClassCode} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="class-code"
            value={values.classCode}
            autoComplete="off"
            spellCheck={false}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.classCode)}
            aria-describedby={
              fieldErrors.classCode ? "class-code-error" : "class-code-hint"
            }
            onChange={(e) =>
              setValues((v) => ({ ...v, classCode: e.target.value.toUpperCase() }))
            }
          />
          <p id="class-code-hint" className="mt-1 text-small text-text-secondary">
            {classSubjectCopy.codeHint}
          </p>
          {fieldErrors.classCode ? (
            <p
              id="class-code-error"
              className="mt-1 text-small text-danger-600"
              role="alert"
            >
              {fieldErrors.classCode}
            </p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="class-name">
            {classSubjectCopy.fieldClassName} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="class-name"
            value={values.className}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.className)}
            onChange={(e) => setValues((v) => ({ ...v, className: e.target.value }))}
          />
          {fieldErrors.className ? (
            <p className="mt-1 text-small text-danger-600" role="alert">
              {fieldErrors.className}
            </p>
          ) : null}
        </div>
      </fieldset>

      <fieldset className="flex flex-col gap-4 rounded-md border border-border bg-surface-raised p-4">
        <legend className="px-1 text-h2 font-semibold text-primary-700">
          {classSubjectCopy.sectionSubject}
        </legend>

        <div>
          <Label htmlFor="subject-code">
            {classSubjectCopy.fieldSubjectCode} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="subject-code"
            value={values.subjectCode}
            autoComplete="off"
            spellCheck={false}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.subjectCode)}
            aria-describedby={
              fieldErrors.subjectCode ? "subject-code-error" : "subject-code-hint"
            }
            onChange={(e) =>
              setValues((v) => ({ ...v, subjectCode: e.target.value.toUpperCase() }))
            }
          />
          <p id="subject-code-hint" className="mt-1 text-small text-text-secondary">
            {classSubjectCopy.codeHint}
          </p>
          {fieldErrors.subjectCode ? (
            <p
              id="subject-code-error"
              className="mt-1 text-small text-danger-600"
              role="alert"
            >
              {fieldErrors.subjectCode}
            </p>
          ) : null}
        </div>

        <div>
          <Label htmlFor="subject-name">
            {classSubjectCopy.fieldSubjectName} <span aria-hidden="true">*</span>
          </Label>
          <Input
            id="subject-name"
            value={values.subjectName}
            aria-required="true"
            aria-invalid={Boolean(fieldErrors.subjectName)}
            onChange={(e) => setValues((v) => ({ ...v, subjectName: e.target.value }))}
          />
          {fieldErrors.subjectName ? (
            <p className="mt-1 text-small text-danger-600" role="alert">
              {fieldErrors.subjectName}
            </p>
          ) : null}
        </div>
      </fieldset>

      <div className="flex flex-wrap justify-end gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => navigate("/admin/rosters")}
        >
          {classSubjectCopy.cancelButton}
        </Button>
        <Button
          type="submit"
          loading={submitting}
          data-testid="class-subject-form-submit"
        >
          {classSubjectCopy.saveButton}
        </Button>
      </div>
    </form>
  );
}
