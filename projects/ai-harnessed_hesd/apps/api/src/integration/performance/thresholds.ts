/**
 * AC-20 AC-21 AC-22 NFR-01 NFR-02 NFR-03 — performance smoke threshold gates.
 */

export const PERFORMANCE_SMOKE_THRESHOLDS = {
  /** AC-20 / NFR-01 — median end-to-end check-in latency */
  medianCheckInMs: 30_000,
  /** AC-22 / NFR-03 — valid rule-pass request processing success rate */
  validSuccessRateMin: 0.99,
  /** AC-21 / NFR-02 — majority of enrolled students within completion window */
  majorityCompletionRateMin: 0.5,
  /** AC-21 / NFR-02 — window from session openedAt */
  completionWindowMs: 5 * 60_000,
} as const;

export type ThresholdVerdict = {
  pass: boolean;
  metric: string;
  threshold: number;
  actual: number;
};

export function computeMedian(values: number[]): number {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1]! + sorted[mid]!) / 2;
  }
  return sorted[mid]!;
}

export function evaluateMedianLatencyGate(latenciesMs: number[]): ThresholdVerdict {
  const actual = computeMedian(latenciesMs);
  return {
    pass: actual < PERFORMANCE_SMOKE_THRESHOLDS.medianCheckInMs,
    metric: "medianCheckInMs",
    threshold: PERFORMANCE_SMOKE_THRESHOLDS.medianCheckInMs,
    actual,
  };
}

export function evaluateSuccessRateGate(successes: number, attempts: number): ThresholdVerdict {
  const actual = attempts === 0 ? 0 : successes / attempts;
  return {
    pass: actual >= PERFORMANCE_SMOKE_THRESHOLDS.validSuccessRateMin,
    metric: "validSuccessRate",
    threshold: PERFORMANCE_SMOKE_THRESHOLDS.validSuccessRateMin,
    actual,
  };
}

export function evaluateMajorityCompletionGate(completed: number, enrolled: number): ThresholdVerdict {
  const actual = enrolled === 0 ? 0 : completed / enrolled;
  return {
    pass: actual > PERFORMANCE_SMOKE_THRESHOLDS.majorityCompletionRateMin,
    metric: "majorityCompletionRate",
    threshold: PERFORMANCE_SMOKE_THRESHOLDS.majorityCompletionRateMin,
    actual,
  };
}

export function isWithinCompletionWindow(
  checkInAt: Date,
  openedAt: Date,
  windowMs: number = PERFORMANCE_SMOKE_THRESHOLDS.completionWindowMs,
): boolean {
  const elapsed = checkInAt.getTime() - openedAt.getTime();
  return elapsed >= 0 && elapsed <= windowMs;
}
