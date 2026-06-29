/**
 * Domain timing and geo bounds referenced by business rules.
 */

/** BR-03 — QR token absolute validity window. */
export const QR_TOKEN_TTL_MS = 30_000;

/** BR-01 — Attendance window after scheduled start. */
export const ATTENDANCE_WINDOW_MS = 10 * 60 * 1000;

/** BR-10 — Instructor manual edit window after session close. */
export const INSTRUCTOR_EDIT_WINDOW_MS = 24 * 60 * 60 * 1000;

/** BR-02 / FR-04 — Default and allowed GPS radius (meters). */
export const GPS_RADIUS_DEFAULT_METERS = 100;
export const GPS_RADIUS_MIN_METERS = 20;
export const GPS_RADIUS_MAX_METERS = 500;

/** FR-02 / NFR-16 — Session inactivity policy bounds (hours). */
export const SESSION_INACTIVITY_DEFAULT_HOURS = 8;
export const SESSION_INACTIVITY_MIN_HOURS = 4;
export const SESSION_INACTIVITY_MAX_HOURS = 12;
export const SESSION_INACTIVITY_DEFAULT_MS =
  SESSION_INACTIVITY_DEFAULT_HOURS * 60 * 60 * 1000;

/** API session cookie name per 05-api-design.md §2.1 */
export const SESSION_COOKIE_NAME = "wecheck_session";
