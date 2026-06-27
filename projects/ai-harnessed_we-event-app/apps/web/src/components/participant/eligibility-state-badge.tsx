import type { CertificateEligibilityState } from "@we-event/domain";

import { Badge } from "@/components/ui/badge";
import { eligibilityStateLabel } from "@/lib/domain-labels";

export function EligibilityStateBadge({ state }: { state: CertificateEligibilityState }) {
  const { label, badgeStatus } = eligibilityStateLabel(state);
  return (
    <Badge status={badgeStatus} aria-label={`Eligibility: ${label}`}>
      {label}
    </Badge>
  );
}
