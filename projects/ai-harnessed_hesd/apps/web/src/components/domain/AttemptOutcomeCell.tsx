import { StatusBadge } from "../ui/StatusBadge";
import {
  attemptOutcomeLabel,
  attemptOutcomeTooltip,
  isRejectedAttemptOutcome,
} from "../../lib/i18n/attempt-outcomes";
import styles from "./AttemptOutcomeCell.module.css";

export interface AttemptOutcomeCellProps {
  outcome: string | null | undefined;
}

export function AttemptOutcomeCell({ outcome }: AttemptOutcomeCellProps) {
  if (!isRejectedAttemptOutcome(outcome)) {
    return <span className={styles.attemptCell}>—</span>;
  }

  const label = attemptOutcomeLabel(outcome);
  const tooltip = attemptOutcomeTooltip(outcome);
  if (!label) {
    return <span className={styles.attemptCell}>—</span>;
  }

  const variant =
    outcome === "DuplicateCheckIn"
      ? "gray"
      : outcome === "OutOfRadius" || outcome === "GpsDisabled" || outcome === "LowAccuracy"
        ? "warning"
        : "danger";

  return (
    <span className={styles.attemptCell} title={tooltip ?? undefined}>
      <StatusBadge
        className={styles.tooltipBadge}
        label={label}
        variant={variant}
        pill
        aria-label={tooltip ? `${label}: ${tooltip}` : label}
      />
    </span>
  );
}
