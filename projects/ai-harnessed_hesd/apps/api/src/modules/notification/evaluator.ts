import type { AttendancePolicyRecord, PolicyScopeType } from "../policy-engine/types.js";

const PRECEDENCE: PolicyScopeType[] = ["ClassSection", "Course", "Faculty", "Institution"];

export type ClosedSessionAttendanceStatus =
  | "Absent"
  | "Present"
  | "Late"
  | "Excused"
  | "Manual Present"
  | "Pending";

/** BR-17 — unexcused absence rate from closed-session attendance rows. */
export function computeUnexcusedAbsenceRate(
  statuses: ClosedSessionAttendanceStatus[],
  excusedCountsTowardThreshold: boolean,
): AbsenceRateComputation {
  let unexcusedAbsentCount = 0;
  let eligibleSessionCount = 0;

  for (const status of statuses) {
    if (!excusedCountsTowardThreshold && status === "Excused") {
      continue;
    }
    eligibleSessionCount += 1;
    if (status === "Absent") {
      unexcusedAbsentCount += 1;
    }
  }

  const unexcusedAbsenceRate =
    eligibleSessionCount === 0
      ? 0
      : Number(((unexcusedAbsentCount / eligibleSessionCount) * 100).toFixed(2));

  return {
    unexcusedAbsentCount,
    eligibleSessionCount,
    unexcusedAbsenceRate,
  };
}

export interface AbsenceRateComputation {
  unexcusedAbsentCount: number;
  eligibleSessionCount: number;
  unexcusedAbsenceRate: number;
}

/** BR-17 strict exceed — rate must be greater than threshold, not equal. */
export function exceedsAbsenceThreshold(
  unexcusedAbsenceRate: number,
  absenceThresholdPercent: number,
): boolean {
  return unexcusedAbsenceRate > absenceThresholdPercent;
}

/** Resolve configured threshold only when a policy level explicitly overrides the field. */
export function resolveConfiguredAbsenceThreshold(
  policies: Partial<Record<PolicyScopeType, AttendancePolicyRecord>>,
): number | null {
  for (const scope of PRECEDENCE) {
    const policy = policies[scope];
    if (policy?.fieldOverrides?.absenceThresholdPercent) {
      return policy.absenceThresholdPercent;
    }
  }
  return null;
}

export function resolveExcusedCountsTowardThreshold(
  policies: Partial<Record<PolicyScopeType, AttendancePolicyRecord>>,
  fallback = false,
): boolean {
  for (const scope of PRECEDENCE) {
    const policy = policies[scope];
    if (policy?.fieldOverrides?.excusedCountsTowardThreshold) {
      return policy.excusedCountsTowardThreshold;
    }
  }
  return fallback;
}
