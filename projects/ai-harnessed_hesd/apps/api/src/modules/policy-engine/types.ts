export type PolicyScopeType = "Institution" | "Faculty" | "Course" | "ClassSection";

export const POLICY_SCOPE_TYPES: readonly PolicyScopeType[] = [
  "Institution",
  "Faculty",
  "Course",
  "ClassSection",
] as const;

export const POLICY_FIELD_KEYS = [
  "checkInOpeningOffsetMinutes",
  "presentWindowMinutes",
  "lateWindowMinutes",
  "autoCloseEnabled",
  "absenceThresholdPercent",
  "excusedCountsTowardThreshold",
  "manualEditWindowHours",
  "adminApprovalRequired",
  "gpsRequired",
  "gpsRadiusMeters",
  "gpsMinAccuracyMeters",
] as const;

export type PolicyFieldKey = (typeof POLICY_FIELD_KEYS)[number];

export type FieldOverrides = Partial<Record<PolicyFieldKey, boolean>>;

export interface AttendancePolicyRecord {
  id: string;
  scopeType: PolicyScopeType;
  scopeId: string | null;
  checkInOpeningOffsetMinutes: number | null;
  presentWindowMinutes: number;
  lateWindowMinutes: number;
  autoCloseEnabled: boolean;
  absenceThresholdPercent: number | null;
  excusedCountsTowardThreshold: boolean;
  manualEditWindowHours: number;
  adminApprovalRequired: boolean;
  gpsRequired: boolean;
  gpsRadiusMeters: number | null;
  gpsMinAccuracyMeters: number | null;
  effectiveFrom: string | null;
  effectiveTo: string | null;
  isActive: boolean;
  fieldOverrides: FieldOverrides;
  createdAt: string;
}

export interface EffectivePolicyValues {
  checkInOpeningOffsetMinutes: number | null;
  presentWindowMinutes: number;
  lateWindowMinutes: number;
  autoCloseEnabled: boolean;
  absenceThresholdPercent: number | null;
  excusedCountsTowardThreshold: boolean;
  manualEditWindowHours: number;
  adminApprovalRequired: boolean;
  gpsRequired: boolean;
  gpsRadiusMeters: number | null;
  gpsMinAccuracyMeters: number | null;
}

export interface ResolvedField<T> {
  value: T;
  source: PolicyScopeType;
}

export type ResolvedEffectivePolicy = {
  [K in keyof EffectivePolicyValues]: ResolvedField<EffectivePolicyValues[K]>;
};

export interface SectionHierarchy {
  classSectionId: string;
  courseId: string;
  facultyId: string;
}

export interface PolicyCreateInput {
  scopeType: PolicyScopeType;
  scopeId?: string | null;
  checkInOpeningOffsetMinutes?: number | null;
  presentWindowMinutes: number;
  lateWindowMinutes: number;
  autoCloseEnabled?: boolean;
  absenceThresholdPercent?: number | null;
  excusedCountsTowardThreshold?: boolean;
  manualEditWindowHours: number;
  adminApprovalRequired?: boolean;
  gpsRequired?: boolean;
  gpsRadiusMeters?: number | null;
  gpsMinAccuracyMeters?: number | null;
  effectiveFrom?: string | null;
  effectiveTo?: string | null;
  fieldOverrides: FieldOverrides;
}

export interface PolicyUpdateInput {
  checkInOpeningOffsetMinutes?: number | null;
  presentWindowMinutes?: number;
  lateWindowMinutes?: number;
  autoCloseEnabled?: boolean;
  absenceThresholdPercent?: number | null;
  excusedCountsTowardThreshold?: boolean;
  manualEditWindowHours?: number;
  adminApprovalRequired?: boolean;
  gpsRequired?: boolean;
  gpsRadiusMeters?: number | null;
  gpsMinAccuracyMeters?: number | null;
  effectiveFrom?: string | null;
  effectiveTo?: string | null;
  fieldOverrides?: FieldOverrides;
}

export interface GpsPayload {
  latitude: number;
  longitude: number;
  accuracyMeters: number;
  permissionDenied?: boolean;
}
