/** Pure absence rate logic — BR-05, FR-16 */

export interface AbsenceRateInput {
  unexcusedAbsenceCount: number;
  sessionCount: number;
}

export interface AbsenceRateResult extends AbsenceRateInput {
  absenceRate: number;
}

export const DEFAULT_ABSENCE_THRESHOLD_PERCENT = 20;

export function computeAbsenceRate(input: AbsenceRateInput): AbsenceRateResult {
  const { unexcusedAbsenceCount, sessionCount } = input;
  if (sessionCount <= 0) {
    return { unexcusedAbsenceCount, sessionCount, absenceRate: 0 };
  }
  return {
    unexcusedAbsenceCount,
    sessionCount,
    absenceRate: unexcusedAbsenceCount / sessionCount,
  };
}

/** BR-05: rate must be strictly greater than threshold (not equal). */
export function exceedsAbsenceThreshold(
  absenceRate: number,
  thresholdPercent: number,
): boolean {
  return absenceRate > thresholdPercent / 100;
}
