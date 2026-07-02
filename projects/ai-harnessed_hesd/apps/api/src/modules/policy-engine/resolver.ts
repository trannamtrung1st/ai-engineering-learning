import { INSTITUTION_POLICY_DEFAULTS } from "./defaults.js";
import type {
  AttendancePolicyRecord,
  EffectivePolicyValues,
  PolicyFieldKey,
  PolicyScopeType,
  ResolvedEffectivePolicy,
  ResolvedField,
  SectionHierarchy,
} from "./types.js";

const PRECEDENCE: PolicyScopeType[] = ["ClassSection", "Course", "Faculty", "Institution"];

function policyAtScope(
  policies: Partial<Record<PolicyScopeType, AttendancePolicyRecord>>,
  scope: PolicyScopeType,
): AttendancePolicyRecord | undefined {
  return policies[scope];
}

function readField(
  policy: AttendancePolicyRecord,
  key: PolicyFieldKey,
): EffectivePolicyValues[PolicyFieldKey] {
  return policy[key];
}

function resolveField<K extends PolicyFieldKey>(
  policies: Partial<Record<PolicyScopeType, AttendancePolicyRecord>>,
  key: K,
): ResolvedField<EffectivePolicyValues[K]> {
  for (const scope of PRECEDENCE) {
    const policy = policyAtScope(policies, scope);
    if (policy?.fieldOverrides[key]) {
      return {
        value: readField(policy, key) as EffectivePolicyValues[K],
        source: scope,
      };
    }
  }

  return {
    value: INSTITUTION_POLICY_DEFAULTS[key],
    source: "Institution",
  };
}

/** BR-20 — merge per-field precedence section > course > faculty > institution. */
export function resolveEffectivePolicyFromRows(
  policies: Partial<Record<PolicyScopeType, AttendancePolicyRecord>>,
): ResolvedEffectivePolicy {
  return {
    checkInOpeningOffsetMinutes: resolveField(policies, "checkInOpeningOffsetMinutes"),
    presentWindowMinutes: resolveField(policies, "presentWindowMinutes"),
    lateWindowMinutes: resolveField(policies, "lateWindowMinutes"),
    autoCloseEnabled: resolveField(policies, "autoCloseEnabled"),
    absenceThresholdPercent: resolveField(policies, "absenceThresholdPercent"),
    excusedCountsTowardThreshold: resolveField(policies, "excusedCountsTowardThreshold"),
    manualEditWindowHours: resolveField(policies, "manualEditWindowHours"),
    adminApprovalRequired: resolveField(policies, "adminApprovalRequired"),
    gpsRequired: resolveField(policies, "gpsRequired"),
    gpsRadiusMeters: resolveField(policies, "gpsRadiusMeters"),
    gpsMinAccuracyMeters: resolveField(policies, "gpsMinAccuracyMeters"),
  };
}

export function flattenResolvedPolicy(resolved: ResolvedEffectivePolicy): EffectivePolicyValues {
  return {
    checkInOpeningOffsetMinutes: resolved.checkInOpeningOffsetMinutes.value,
    presentWindowMinutes: resolved.presentWindowMinutes.value,
    lateWindowMinutes: resolved.lateWindowMinutes.value,
    autoCloseEnabled: resolved.autoCloseEnabled.value,
    absenceThresholdPercent: resolved.absenceThresholdPercent.value,
    excusedCountsTowardThreshold: resolved.excusedCountsTowardThreshold.value,
    manualEditWindowHours: resolved.manualEditWindowHours.value,
    adminApprovalRequired: resolved.adminApprovalRequired.value,
    gpsRequired: resolved.gpsRequired.value,
    gpsRadiusMeters: resolved.gpsRadiusMeters.value,
    gpsMinAccuracyMeters: resolved.gpsMinAccuracyMeters.value,
  };
}

export function indexPoliciesByScope(
  rows: AttendancePolicyRecord[],
  hierarchy: SectionHierarchy,
): Partial<Record<PolicyScopeType, AttendancePolicyRecord>> {
  const indexed: Partial<Record<PolicyScopeType, AttendancePolicyRecord>> = {};

  for (const row of rows) {
    if (!row.isActive) continue;

    switch (row.scopeType) {
      case "Institution":
        if (row.scopeId === null) indexed.Institution = row;
        break;
      case "Faculty":
        if (row.scopeId === hierarchy.facultyId) indexed.Faculty = row;
        break;
      case "Course":
        if (row.scopeId === hierarchy.courseId) indexed.Course = row;
        break;
      case "ClassSection":
        if (row.scopeId === hierarchy.classSectionId) indexed.ClassSection = row;
        break;
      default:
        break;
    }
  }

  return indexed;
}
