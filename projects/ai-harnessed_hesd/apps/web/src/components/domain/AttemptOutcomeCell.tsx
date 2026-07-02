import { ErrorCode } from "@attendly/domain";
import { StatusBadge } from "../ui/StatusBadge";
import {
  attemptOutcomeLabel,
  attemptOutcomeTooltip,
  formatOutOfRadiusReviewMeta,
  isRejectedAttemptOutcome,
} from "../../lib/i18n/attempt-outcomes";
import styles from "./AttemptOutcomeCell.module.css";

export interface AttemptOutcomeCellProps {
  outcome: string | null | undefined;
  distanceMeters?: number | null;
  allowedRadiusMeters?: number | null;
}

export function AttemptOutcomeCell({
  outcome,
  distanceMeters,
  allowedRadiusMeters,
}: AttemptOutcomeCellProps) {
  if (!isRejectedAttemptOutcome(outcome)) {
    return <span className={styles.attemptCell}>—</span>;
  }

  const label = attemptOutcomeLabel(outcome);
  const tooltip = attemptOutcomeTooltip(outcome);
  if (!label) {
    return <span className={styles.attemptCell}>—</span>;
  }

  const reviewMeta =
    outcome === ErrorCode.OutOfRadius
      ? formatOutOfRadiusReviewMeta(distanceMeters, allowedRadiusMeters)
      : null;
  const ariaLabel = reviewMeta
    ? `${label}: ${reviewMeta}`
    : tooltip
      ? `${label}: ${tooltip}`
      : label;

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
        aria-label={ariaLabel}
      />
      {reviewMeta ? (
        <span className={styles.reviewMeta} data-testid="attempt-outcome-distance">
          {reviewMeta}
        </span>
      ) : null}
    </span>
  );
}
