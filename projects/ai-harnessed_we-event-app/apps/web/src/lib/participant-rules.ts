import type { EventState, RegistrationState } from "@we-event/domain";

/** Aligns with API `ACTIVE_REGISTRATION_STATES` in registration/validation.ts */
const ACTIVE_REGISTRATION_STATES: RegistrationState[] = [
  "Requested",
  "Registered",
  "Waitlisted",
  "CheckedIn",
];

function hasActiveRegistration(state: RegistrationState | null | undefined): boolean {
  return state != null && ACTIVE_REGISTRATION_STATES.includes(state);
}

export function isWithinTimeWindow(
  openAt: string,
  closeAt: string,
  now: number = Date.now(),
): boolean {
  const open = new Date(openAt).getTime();
  const close = new Date(closeAt).getTime();
  if (Number.isNaN(open) || Number.isNaN(close)) {
    return false;
  }
  return now >= open && now <= close;
}

/** Mirrors API `assertCheckinWindowOpen` — close boundary is exclusive. */
export function isWithinCheckinWindow(
  openAt: string,
  closeAt: string,
  now: number = Date.now(),
): boolean {
  const open = new Date(openAt).getTime();
  const close = new Date(closeAt).getTime();
  if (Number.isNaN(open) || Number.isNaN(close)) {
    return false;
  }
  return now >= open && now < close;
}

/** Mirrors API `assertRegistrationWindowOpen` + `assertNoDuplicateActive` for UX gating. */
export function canRegister(
  eventState: EventState,
  registrationPaused: boolean,
  registrationOpenAt: string,
  registrationCloseAt: string,
  registrationState: RegistrationState | null | undefined,
  now: number = Date.now(),
): boolean {
  return (
    eventState === "RegistrationOpen" &&
    !registrationPaused &&
    isWithinTimeWindow(registrationOpenAt, registrationCloseAt, now) &&
    !hasActiveRegistration(registrationState)
  );
}

/** Mirrors API `assertParticipantCancellationAllowed` for UX gating. */
export function canCancelRegistration(
  registrationState: RegistrationState | null | undefined,
  registrationCloseAt: string,
  now: number = Date.now(),
): boolean {
  if (registrationState !== "Registered" && registrationState !== "Waitlisted") {
    return false;
  }
  const close = new Date(registrationCloseAt).getTime();
  if (Number.isNaN(close)) {
    return false;
  }
  return now <= close;
}

/** Mirrors API `assertSelfCheckinAllowed` + registration/window checks for UX gating. */
export function canSelfCheckIn(
  eventState: EventState,
  registrationState: RegistrationState | null | undefined,
  checkinOpenAt: string,
  checkinCloseAt: string,
  selfCheckinEnabled: boolean = true,
  now: number = Date.now(),
): boolean {
  return (
    selfCheckinEnabled &&
    eventState === "InProgress" &&
    registrationState === "Registered" &&
    isWithinCheckinWindow(checkinOpenAt, checkinCloseAt, now)
  );
}

/** Mirrors API `assertFeedbackWindowOpen` + registration eligibility for UX gating. */
export function canSubmitFeedback(
  eventState: EventState,
  registrationState: RegistrationState | null | undefined,
  feedbackOpenAt: string,
  feedbackCloseAt: string,
  now: number = Date.now(),
): boolean {
  return (
    eventState === "Completed" &&
    registrationState === "Attended" &&
    isWithinTimeWindow(feedbackOpenAt, feedbackCloseAt, now)
  );
}

export function canViewEligibility(
  eventState: EventState,
  registrationState: RegistrationState | null | undefined,
): boolean {
  return (
    eventState === "Completed" &&
    (registrationState === "Attended" || registrationState === "Absent")
  );
}
