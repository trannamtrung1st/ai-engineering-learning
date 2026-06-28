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
