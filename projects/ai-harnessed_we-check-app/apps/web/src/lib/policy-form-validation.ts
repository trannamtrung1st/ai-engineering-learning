import { policyCopy } from "@/lib/copy/policy-labels";

export interface PolicyFormValues {
  absenceThresholdPercent: string;
  autoWarningEnabled: boolean;
}

export function validatePolicyForm(
  values: PolicyFormValues,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const trimmed = values.absenceThresholdPercent.trim();

  if (!trimmed) {
    errors.absenceThresholdPercent = policyCopy.thresholdRequired;
    return errors;
  }

  const parsed = Number.parseInt(trimmed, 10);
  if (
    Number.isNaN(parsed) ||
    !Number.isInteger(parsed) ||
    parsed < 1 ||
    parsed > 100
  ) {
    errors.absenceThresholdPercent = policyCopy.thresholdRange;
  }

  return errors;
}
