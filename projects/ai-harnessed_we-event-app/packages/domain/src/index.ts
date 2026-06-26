/**
 * Shared domain package — enums, state machines, and validation identifiers.
 *
 * This module is intentionally framework-agnostic so it can be shared
 * between backend and frontend without pulling in runtime dependencies.
 */

export const DOMAIN_PACKAGE_VERSION = "0.0.1";

/**
 * Canonical actor roles for RBAC (see docs/technical/01-roles-permissions.md).
 */
export const ACTOR_ROLES = [
  "OrganizerAdmin",
  "OrganizerStaff",
  "Participant",
] as const;

export type ActorRole = (typeof ACTOR_ROLES)[number];

/**
 * Event aggregate lifecycle states (see docs/technical/07-state-machines.md).
 */
export const EVENT_STATES = [
  "Draft",
  "Published",
  "RegistrationOpen",
  "RegistrationClosed",
  "InProgress",
  "Completed",
  "Archived",
  "Cancelled",
] as const;

export type EventState = (typeof EVENT_STATES)[number];

export const EVENT_TRANSITION_TRIGGERS = [
  "publishEvent",
  "openRegistrationWindow",
  "closeRegistrationWindow",
  "startEvent",
  "endEvent",
  "archiveEvent",
  "cancelEvent",
] as const;

export type EventTransitionTrigger =
  (typeof EVENT_TRANSITION_TRIGGERS)[number];

export interface EventStateTransition {
  from: EventState;
  to: EventState;
  trigger: EventTransitionTrigger;
}

/**
 * Canonical event state machine transitions.
 */
export const EVENT_STATE_TRANSITIONS: readonly EventStateTransition[] = [
  { from: "Draft", to: "Published", trigger: "publishEvent" },
  {
    from: "Published",
    to: "RegistrationOpen",
    trigger: "openRegistrationWindow",
  },
  {
    from: "RegistrationOpen",
    to: "RegistrationClosed",
    trigger: "closeRegistrationWindow",
  },
  { from: "RegistrationClosed", to: "InProgress", trigger: "startEvent" },
  { from: "InProgress", to: "Completed", trigger: "endEvent" },
  { from: "Completed", to: "Archived", trigger: "archiveEvent" },
  { from: "Published", to: "Cancelled", trigger: "cancelEvent" },
  { from: "RegistrationOpen", to: "Cancelled", trigger: "cancelEvent" },
  { from: "RegistrationClosed", to: "Cancelled", trigger: "cancelEvent" },
] as const;

export function isValidEventTransition(
  from: EventState,
  to: EventState,
): boolean {
  return EVENT_STATE_TRANSITIONS.some(
    (transition) => transition.from === from && transition.to === to,
  );
}

/**
 * Registration aggregate lifecycle states.
 */
export const REGISTRATION_STATES = [
  "Requested",
  "Registered",
  "Waitlisted",
  "Rejected",
  "CancelledByUser",
  "CancelledByOrganizer",
  "CheckedIn",
  "Attended",
  "Absent",
  "Expired",
] as const;

export type RegistrationState = (typeof REGISTRATION_STATES)[number];

export const REGISTRATION_TRANSITION_TRIGGERS = [
  "acceptRegistration",
  "queueWaitlist",
  "rejectRegistration",
  "promoteFromWaitlist",
  "cancelByParticipant",
  "cancelByOrganizer",
  "validCheckin",
  "markAttendance",
  "eventCompletedWithoutCheckin",
  "registrationClosed",
] as const;

export type RegistrationTransitionTrigger =
  (typeof REGISTRATION_TRANSITION_TRIGGERS)[number];

export interface RegistrationStateTransition {
  from: RegistrationState;
  to: RegistrationState;
  trigger: RegistrationTransitionTrigger;
}

export const REGISTRATION_STATE_TRANSITIONS: readonly RegistrationStateTransition[] =
  [
    { from: "Requested", to: "Registered", trigger: "acceptRegistration" },
    { from: "Requested", to: "Waitlisted", trigger: "queueWaitlist" },
    { from: "Requested", to: "Rejected", trigger: "rejectRegistration" },
    { from: "Waitlisted", to: "Registered", trigger: "promoteFromWaitlist" },
    { from: "Registered", to: "CancelledByUser", trigger: "cancelByParticipant" },
    {
      from: "Registered",
      to: "CancelledByOrganizer",
      trigger: "cancelByOrganizer",
    },
    { from: "Registered", to: "CheckedIn", trigger: "validCheckin" },
    { from: "CheckedIn", to: "Attended", trigger: "markAttendance" },
    {
      from: "Registered",
      to: "Absent",
      trigger: "eventCompletedWithoutCheckin",
    },
    { from: "Waitlisted", to: "Expired", trigger: "registrationClosed" },
  ] as const;

export function isValidRegistrationTransition(
  from: RegistrationState,
  to: RegistrationState,
): boolean {
  return REGISTRATION_STATE_TRANSITIONS.some(
    (transition) => transition.from === from && transition.to === to,
  );
}

/**
 * Certificate eligibility lifecycle states.
 */
export const CERTIFICATE_ELIGIBILITY_STATES = [
  "PendingEvaluation",
  "Eligible",
  "NotEligible",
  "Revoked",
] as const;

export type CertificateEligibilityState =
  (typeof CERTIFICATE_ELIGIBILITY_STATES)[number];

export const CERTIFICATE_ELIGIBILITY_TRANSITION_TRIGGERS = [
  "passAllRules",
  "failAnyRule",
  "adminRevokeWithReason",
] as const;

export type CertificateEligibilityTransitionTrigger =
  (typeof CERTIFICATE_ELIGIBILITY_TRANSITION_TRIGGERS)[number];

export interface CertificateEligibilityStateTransition {
  from: CertificateEligibilityState;
  to: CertificateEligibilityState;
  trigger: CertificateEligibilityTransitionTrigger;
}

export const CERTIFICATE_ELIGIBILITY_STATE_TRANSITIONS: readonly CertificateEligibilityStateTransition[] =
  [
    {
      from: "PendingEvaluation",
      to: "Eligible",
      trigger: "passAllRules",
    },
    {
      from: "PendingEvaluation",
      to: "NotEligible",
      trigger: "failAnyRule",
    },
    {
      from: "Eligible",
      to: "Revoked",
      trigger: "adminRevokeWithReason",
    },
  ] as const;

export function isValidCertificateEligibilityTransition(
  from: CertificateEligibilityState,
  to: CertificateEligibilityState,
): boolean {
  return CERTIFICATE_ELIGIBILITY_STATE_TRANSITIONS.some(
    (transition) => transition.from === from && transition.to === to,
  );
}

/**
 * Canonical domain event names (see docs/technical/03-domain-model.md).
 */
export const DOMAIN_EVENTS = [
  "EventPublished",
  "RegistrationRequested",
  "RegistrationAccepted",
  "RegistrationWaitlisted",
  "RegistrationCancelled",
  "WaitlistPromoted",
  "CheckinRecorded",
  "AttendanceFinalized",
  "FeedbackSubmitted",
  "EligibilityEvaluated",
  "EligibilityRevoked",
  "RuleConfigChanged",
] as const;

export type DomainEventType = (typeof DOMAIN_EVENTS)[number];

/**
 * Business rule identifiers BR-01..BR-22 from docs/technical/08-validation-rules.md.
 */
export const BUSINESS_RULE_IDS = {
  BR_01: "BR-01",
  BR_02: "BR-02",
  BR_03: "BR-03",
  BR_04: "BR-04",
  BR_05: "BR-05",
  BR_06: "BR-06",
  BR_07: "BR-07",
  BR_08: "BR-08",
  BR_09: "BR-09",
  BR_10: "BR-10",
  BR_11: "BR-11",
  BR_12: "BR-12",
  BR_13: "BR-13",
  BR_14: "BR-14",
  BR_15: "BR-15",
  BR_16: "BR-16",
  BR_17: "BR-17",
  BR_18: "BR-18",
  BR_19: "BR-19",
  BR_20: "BR-20",
  BR_21: "BR-21",
  BR_22: "BR-22",
} as const;

export type BusinessRuleId = (typeof BUSINESS_RULE_IDS)[keyof typeof BUSINESS_RULE_IDS];

/**
 * Extended sub-rule identifiers (BR-04a/b, BR-06a/b, BR-08a/b) from
 * docs/technical/08-validation-rules.md.
 */
export const EXTENDED_BUSINESS_RULE_IDS = {
  BR_04A: "BR-04a",
  BR_04B: "BR-04b",
  BR_06A: "BR-06a",
  BR_06B: "BR-06b",
  BR_08A: "BR-08a",
  BR_08B: "BR-08b",
} as const;

export type ExtendedBusinessRuleId =
  (typeof EXTENDED_BUSINESS_RULE_IDS)[keyof typeof EXTENDED_BUSINESS_RULE_IDS];

export type AnyBusinessRuleId = BusinessRuleId | ExtendedBusinessRuleId;

/**
 * Canonical validation error codes surfaced to clients.
 *
 * Only rules that explicitly define error codes in the catalog are included.
 */
export const VALIDATION_ERROR_CODES = {
  REGISTRATION_DUPLICATE_ACTIVE: "REGISTRATION_DUPLICATE_ACTIVE",
  REGISTRATION_WINDOW_CLOSED: "REGISTRATION_WINDOW_CLOSED",
  CAPACITY_EXCEEDED: "CAPACITY_EXCEEDED",
  REGISTRATION_REJECTED_FULL: "REGISTRATION_REJECTED_FULL",
  WAITLIST_ORDER_CONFLICT: "WAITLIST_ORDER_CONFLICT",
  CANCELLATION_DEADLINE_PASSED: "CANCELLATION_DEADLINE_PASSED",
  CANCELLATION_NOT_ALLOWED: "CANCELLATION_NOT_ALLOWED",
  CHECKIN_WINDOW_CLOSED: "CHECKIN_WINDOW_CLOSED",
  CHECKIN_ALREADY_RECORDED: "CHECKIN_ALREADY_RECORDED",
  SELF_CHECKIN_DISABLED: "SELF_CHECKIN_DISABLED",
  AUDIT_METADATA_MISSING: "AUDIT_METADATA_MISSING",
  FEEDBACK_REQUIRED: "FEEDBACK_REQUIRED",
  FEEDBACK_NOT_ALLOWED: "FEEDBACK_NOT_ALLOWED",
  FEEDBACK_DUPLICATE: "FEEDBACK_DUPLICATE",
  NOT_ELIGIBLE_ATTENDANCE: "NOT_ELIGIBLE_ATTENDANCE",
  NOT_ELIGIBLE_FEEDBACK: "NOT_ELIGIBLE_FEEDBACK",
  ELIGIBILITY_REASON_MISSING: "ELIGIBILITY_REASON_MISSING",
  ELIGIBILITY_OVERRIDE_FORBIDDEN: "ELIGIBILITY_OVERRIDE_FORBIDDEN",
  EVENT_RULE_CHANGE_FORBIDDEN: "EVENT_RULE_CHANGE_FORBIDDEN",
  AUDIT_REQUIRED_FOR_CRITICAL_CHANGE: "AUDIT_REQUIRED_FOR_CRITICAL_CHANGE",
} as const;

export type ValidationErrorCode =
  (typeof VALIDATION_ERROR_CODES)[keyof typeof VALIDATION_ERROR_CODES];

/**
 * Mapping from business rule ID to its primary error code, when defined.
 *
 * Some rules are routing or invariant-only and therefore have no public code.
 */
export const RULE_TO_ERROR_CODE: Record<BusinessRuleId, ValidationErrorCode | null> =
  {
    "BR-01": VALIDATION_ERROR_CODES.REGISTRATION_DUPLICATE_ACTIVE,
    "BR-02": VALIDATION_ERROR_CODES.REGISTRATION_WINDOW_CLOSED,
    "BR-03": VALIDATION_ERROR_CODES.CAPACITY_EXCEEDED,
    "BR-04": null,
    "BR-05": VALIDATION_ERROR_CODES.REGISTRATION_REJECTED_FULL,
    "BR-06": VALIDATION_ERROR_CODES.WAITLIST_ORDER_CONFLICT,
    "BR-07": VALIDATION_ERROR_CODES.CANCELLATION_DEADLINE_PASSED,
    "BR-08": null,
    "BR-09": VALIDATION_ERROR_CODES.CANCELLATION_NOT_ALLOWED,
    "BR-10": VALIDATION_ERROR_CODES.CHECKIN_WINDOW_CLOSED,
    "BR-11": VALIDATION_ERROR_CODES.CHECKIN_ALREADY_RECORDED,
    "BR-12": null,
    "BR-13": VALIDATION_ERROR_CODES.AUDIT_METADATA_MISSING,
    "BR-14": VALIDATION_ERROR_CODES.FEEDBACK_REQUIRED,
    "BR-15": VALIDATION_ERROR_CODES.FEEDBACK_NOT_ALLOWED,
    "BR-16": VALIDATION_ERROR_CODES.FEEDBACK_DUPLICATE,
    "BR-17": VALIDATION_ERROR_CODES.NOT_ELIGIBLE_ATTENDANCE,
    "BR-18": VALIDATION_ERROR_CODES.NOT_ELIGIBLE_FEEDBACK,
    "BR-19": VALIDATION_ERROR_CODES.ELIGIBILITY_REASON_MISSING,
    "BR-20": VALIDATION_ERROR_CODES.ELIGIBILITY_OVERRIDE_FORBIDDEN,
    "BR-21": VALIDATION_ERROR_CODES.EVENT_RULE_CHANGE_FORBIDDEN,
    "BR-22": VALIDATION_ERROR_CODES.AUDIT_REQUIRED_FOR_CRITICAL_CHANGE,
  };

/**
 * Error codes for extended sub-rules where the catalog defines a public code.
 */
export const EXTENDED_RULE_TO_ERROR_CODE: Record<
  ExtendedBusinessRuleId,
  ValidationErrorCode | null
> = {
  "BR-04a": null,
  "BR-04b": null,
  "BR-06a": null,
  "BR-06b": VALIDATION_ERROR_CODES.WAITLIST_ORDER_CONFLICT,
  "BR-08a": null,
  "BR-08b": null,
};

