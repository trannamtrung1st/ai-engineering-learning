import type { EffectivePolicyValues } from "./types.js";

/** MVP institution defaults — docs/brds/04-business-rules.md §1 */
export const INSTITUTION_POLICY_DEFAULTS: EffectivePolicyValues = {
  checkInOpeningOffsetMinutes: 0,
  presentWindowMinutes: 15,
  lateWindowMinutes: 15,
  autoCloseEnabled: true,
  absenceThresholdPercent: 20,
  excusedCountsTowardThreshold: false,
  manualEditWindowHours: 24,
  adminApprovalRequired: false,
  gpsRequired: false,
  gpsRadiusMeters: 100,
  gpsMinAccuracyMeters: null,
};

export const ALL_POLICY_FIELD_OVERRIDES = {
  checkInOpeningOffsetMinutes: true,
  presentWindowMinutes: true,
  lateWindowMinutes: true,
  autoCloseEnabled: true,
  absenceThresholdPercent: true,
  excusedCountsTowardThreshold: true,
  manualEditWindowHours: true,
  adminApprovalRequired: true,
  gpsRequired: true,
  gpsRadiusMeters: true,
  gpsMinAccuracyMeters: true,
} as const;
