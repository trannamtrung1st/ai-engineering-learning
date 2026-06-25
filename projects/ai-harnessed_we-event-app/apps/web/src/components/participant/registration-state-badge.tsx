import type { RegistrationState } from "@we-event/domain";

import { Badge } from "@/components/ui/badge";
import { registrationStateLabel } from "@/lib/domain-labels";

export function RegistrationStateBadge({ state }: { state: RegistrationState }) {
  const { label, badgeStatus } = registrationStateLabel(state);
  return (
    <Badge status={badgeStatus} aria-label={`Registration status: ${label}`}>
      {label}
    </Badge>
  );
}
