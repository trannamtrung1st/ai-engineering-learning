# Spec: Core attendance check-in

**Status:** approved

## Goal

Deliver the thinnest end-to-end Attendly loop: a lecturer opens a class session and shows a rotating QR; an enrolled, logged-in student checks in once and gets Present (or a clear rejection); the lecturer can manually mark a student when self check-in fails. Seed data replaces school import for this learning/demo build.

## Requirements

- WHEN a lecturer opens attendance for a class session they own THEN the system starts a short-lived multi-use QR session token bound to that session (default TTL ~30s) and refreshes it while attendance stays open
- WHEN multiple enrolled students submit a still-valid QR token for that open session THEN each eligible student can succeed independently (token is not one-time global)
- WHEN a student is not logged in and opens the check-in flow THEN they are redirected to login before attendance can be recorded
- WHEN an enrolled, logged-in student submits a valid token for an open session and has not already succeeded THEN the system records Present with a check-in timestamp and method QR
- WHEN the QR token is expired, wrong session, or attendance is closed/not open THEN the system rejects the check-in and records a failed attempt with a reason
- WHEN the student is not enrolled in the class section THEN the system rejects the check-in and records a failed attempt
- WHEN the student already has a successful attendance record for that session THEN a further check-in is rejected with a clear “already checked in” outcome
- WHEN self check-in failed or is unavailable THEN the owning lecturer can set Manual Present (or equivalent manual status) for that student on that session
- WHEN a lecturer saves a manual attendance change THEN an audit entry records who changed what, when, old value, new value, and reason
- WHEN the product is started for demo THEN seed data provides at least one lecturer, one class section, enrollments, and a class session so the loop can be exercised without CSV/SIS import

## Out of scope

- GPS validation, suspicious-location review, and mock-location detection (Phase 1 Should / later hardening in the BRD)
- Full Phase 1 extras: student CSV/SIS import, realtime dashboard polish, CSV export, Present/Late/Absent/Excused policy engine, absence-threshold alerts
- Roles beyond Student and Lecturer (Department Admin, Academic Admin, IT Admin, System Auditor)
- Native apps, face recognition, SSO/MFA, device binding, continuous location tracking
- School-wide reporting and multi-term academic catalog management beyond what seed data needs

## Acceptance criteria

- [ ] Lecturer can open attendance on a seeded session and see a QR that rotates on TTL while the session is open
- [ ] Two different enrolled students can both check in successfully using the same still-valid QR token
- [ ] Unauthenticated check-in is blocked until login completes
- [ ] Non-enrolled student check-in is rejected with a failed-attempt reason
- [ ] Second successful check-in by the same student for the same session is rejected
- [ ] Expired or wrong-session QR check-in is rejected with a failed-attempt reason
- [ ] Lecturer can manually mark a student Present when needed, and that change appears in an audit log with actor, time, before/after, and reason
- [ ] Demo path works from seed data alone (no import pipeline required)
