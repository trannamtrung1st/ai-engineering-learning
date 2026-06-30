import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { policyCopy } from "@/lib/copy/policy-labels";
import {
  getAbsencePolicy,
  mapPolicyDetailsToFieldErrors,
  updateAbsencePolicy,
  type AbsencePolicyDto,
} from "@/lib/policy-api";
import {
  validatePolicyForm,
  type PolicyFormValues,
} from "@/lib/policy-form-validation";

export interface AttendancePolicyFormProps {
  onSaved?: (policy: AbsencePolicyDto) => void;
}

/** FR-16 / AC-16 / BR-05 — admin absence threshold and auto-warning configuration */
export function AttendancePolicyForm({ onSaved }: AttendancePolicyFormProps) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [values, setValues] = useState<PolicyFormValues>({
    absenceThresholdPercent: "20",
    autoWarningEnabled: false,
  });
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const initialValuesRef = useRef<PolicyFormValues | null>(null);
  const submitInFlightRef = useRef(false);

  async function loadPolicy() {
    setLoading(true);
    setLoadError(false);
    const result = await getAbsencePolicy();
    if (!result.ok) {
      setLoadError(true);
      setLoading(false);
      return;
    }

    const nextValues: PolicyFormValues = {
      absenceThresholdPercent: String(result.data.thresholdPercent),
      autoWarningEnabled: result.data.autoWarningEnabled,
    };
    setValues(nextValues);
    initialValuesRef.current = nextValues;
    setLoading(false);
  }

  useEffect(() => {
    void loadPolicy();
  }, []);

  useEffect(() => {
    const initial = initialValuesRef.current;
    if (!initial) {
      return;
    }

    const dirty =
      values.absenceThresholdPercent !== initial.absenceThresholdPercent ||
      values.autoWarningEnabled !== initial.autoWarningEnabled;

    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    }

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [values]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (submitInFlightRef.current) {
      return;
    }

    const clientErrors = validatePolicyForm(values);
    setFieldErrors(clientErrors);
    setFormError(null);
    if (Object.keys(clientErrors).length > 0) {
      return;
    }

    const payload: AbsencePolicyDto = {
      thresholdPercent: Number.parseInt(values.absenceThresholdPercent, 10),
      autoWarningEnabled: values.autoWarningEnabled,
    };

    submitInFlightRef.current = true;
    setSubmitting(true);

    const result = await updateAbsencePolicy(payload);
    submitInFlightRef.current = false;
    setSubmitting(false);

    if (!result.ok) {
      const apiFieldErrors = mapPolicyDetailsToFieldErrors(result.error.details);
      if (Object.keys(apiFieldErrors).length > 0) {
        const mapped: Record<string, string> = {};
        if (apiFieldErrors.thresholdPercent) {
          mapped.absenceThresholdPercent = apiFieldErrors.thresholdPercent;
        }
        setFieldErrors(mapped);
      } else {
        setFormError(result.error.message ?? policyCopy.saveError);
      }
      return;
    }

    const savedValues: PolicyFormValues = {
      absenceThresholdPercent: String(result.data.thresholdPercent),
      autoWarningEnabled: result.data.autoWarningEnabled,
    };
    setValues(savedValues);
    initialValuesRef.current = savedValues;
    setFieldErrors({});
    toast.success(policyCopy.saveSuccess);
    onSaved?.(result.data);
  }

  if (loading) {
    return (
      <div
        className="flex items-center gap-2 text-body text-text-secondary"
        data-testid="attendance-policy-loading"
        aria-busy="true"
      >
        <Spinner />
        <span>Đang tải chính sách…</span>
      </div>
    );
  }

  if (loadError) {
    return (
      <Alert variant="danger" data-testid="attendance-policy-load-error">
        {policyCopy.loadError}
        <div className="mt-3">
          <Button type="button" variant="outline" onClick={() => void loadPolicy()}>
            {policyCopy.retryButton}
          </Button>
        </div>
      </Alert>
    );
  }

  return (
    <form
      onSubmit={(event) => void handleSubmit(event)}
      noValidate
      className="max-w-lg rounded-md border border-border bg-surface-raised p-6"
      data-testid="attendance-policy-form"
      aria-busy={submitting}
    >
      {formError ? (
        <Alert variant="danger" className="mb-4">
          {formError}
        </Alert>
      ) : null}

      <div>
        <Label htmlFor="absence-threshold-percent">
          {policyCopy.fieldThreshold} <span aria-hidden="true">*</span>
        </Label>
        <Input
          id="absence-threshold-percent"
          type="number"
          min={1}
          max={100}
          step={1}
          inputMode="numeric"
          value={values.absenceThresholdPercent}
          aria-required="true"
          aria-invalid={Boolean(fieldErrors.absenceThresholdPercent)}
          data-testid="absence-threshold-input"
          onChange={(event) =>
            setValues((current) => ({
              ...current,
              absenceThresholdPercent: event.target.value,
            }))
          }
        />
        <p className="mt-1 text-small text-text-secondary">
          {policyCopy.fieldThresholdHint}
        </p>
        {fieldErrors.absenceThresholdPercent ? (
          <p className="mt-1 text-small text-danger-600" role="alert">
            {fieldErrors.absenceThresholdPercent}
          </p>
        ) : null}
      </div>

      <div className="mt-6">
        <div className="flex items-start gap-3">
          <input
            id="auto-warning-enabled"
            type="checkbox"
            className="mt-1 h-5 w-5 rounded border-border"
            checked={values.autoWarningEnabled}
            data-testid="auto-warning-toggle"
            onChange={(event) =>
              setValues((current) => ({
                ...current,
                autoWarningEnabled: event.target.checked,
              }))
            }
          />
          <div>
            <Label htmlFor="auto-warning-enabled">{policyCopy.fieldAutoWarning}</Label>
            <p className="mt-1 text-small text-text-secondary">
              {policyCopy.fieldAutoWarningHint}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-8 flex justify-end">
        <Button
          type="submit"
          loading={submitting}
          disabled={submitting}
          data-testid="attendance-policy-submit"
        >
          {policyCopy.saveButton}
        </Button>
      </div>
    </form>
  );
}
