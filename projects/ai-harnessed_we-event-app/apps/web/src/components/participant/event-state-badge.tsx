import type { EventState } from "@we-event/domain";

import { Badge } from "@/components/ui/badge";
import { eventStateLabel } from "@/lib/domain-labels";

export function EventStateBadge({ state }: { state: EventState }) {
  const { label, badgeStatus } = eventStateLabel(state);
  return (
    <Badge status={badgeStatus} aria-label={`Event status: ${label}`}>
      {label}
    </Badge>
  );
}
