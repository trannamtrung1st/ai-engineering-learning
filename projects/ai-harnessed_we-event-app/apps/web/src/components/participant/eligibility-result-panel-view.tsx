import { EligibilityStateBadge } from "@/components/participant/eligibility-state-badge";
import { Alert } from "@/components/ui/alert";
import { eligibilityStateLabel } from "@/lib/domain-labels";
import { formatDateTime } from "@/lib/format";
import type { EligibilityResult } from "@/lib/participant-api";

export interface EligibilityResultPanelViewProps {
  eligibility: EligibilityResult;
}

export function EligibilityResultPanelView({ eligibility }: EligibilityResultPanelViewProps) {
  const eligibilityLabel = eligibilityStateLabel(eligibility.result);

  return (
    <div className="max-w-xl space-y-4 rounded-[var(--radius-lg)] border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-6">
      <EligibilityStateBadge state={eligibility.result} />

      {eligibilityLabel.hint ? (
        <p className="text-[length:var(--font-size-sm)] text-[var(--color-text-secondary)]">
          {eligibilityLabel.hint}
        </p>
      ) : null}

      {eligibility.reasonText ? (
        <Alert
          variant={eligibility.result === "Eligible" ? "success" : "warning"}
          title={eligibility.reasonCode ?? "Evaluation reason"}
        >
          {eligibility.reasonText}
        </Alert>
      ) : null}

      <dl className="grid gap-3 text-[length:var(--font-size-sm)]">
        <div>
          <dt className="text-[var(--color-text-secondary)]">Evaluated at</dt>
          <dd className="font-[var(--font-weight-medium)]">
            {eligibility.evaluatedAt ? formatDateTime(eligibility.evaluatedAt) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[var(--color-text-secondary)]">Last updated</dt>
          <dd className="font-[var(--font-weight-medium)]">
            {formatDateTime(eligibility.updatedAt)}
          </dd>
        </div>
      </dl>
    </div>
  );
}
