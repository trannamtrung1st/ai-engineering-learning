import type { EventState } from "@we-event/domain";

import { Badge } from "@/components/ui/badge";
import { eventStateLabel } from "@/lib/domain-labels";

export function EventStateBadge({ state }: { state: EventState }) {
  const { label } = eventStateLabel(state);
  return (
    <Badge variant="outline" aria-label={`Event status: ${label}`}>
      {label}
    </Badge>
  );
}
