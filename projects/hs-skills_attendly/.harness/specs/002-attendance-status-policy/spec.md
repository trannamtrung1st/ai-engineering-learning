# Spec: Attendance status and policy

**Status:** approved

## Goal

Extend the shipped check-in loop so successful self check-ins resolve to Present or Late from a per-section policy, closing attendance auto-marks remaining enrolled students Absent, and lecturers can manually set Late / Absent / Excused / Manual Present with audit.

## Requirements

- WHEN a class section has an attendance policy THEN that policy defines a present window (minutes from attendance open) and a late window (minutes after the present window ends, or until attendance closes — whichever comes first for eligibility)
- WHEN an enrolled, logged-in student successfully checks in via a valid QR token within the present window THEN the attendance record status is Present
- WHEN an enrolled, logged-in student successfully checks in via a valid QR token after the present window but while still within the late window and attendance is open THEN the attendance record status is Late
- WHEN a successful check-in would fall after both present and late windows THEN the system rejects the check-in and records a failed attempt with a clear reason (e.g. outside attendance windows)
- WHEN the owning lecturer closes attendance for a session THEN every enrolled student without a successful attendance record for that session receives Absent
- WHEN attendance is already closed THEN further QR self check-in is rejected (existing closed behavior preserved)
- WHEN the owning lecturer manually sets a student’s session status to Present-equivalent Manual Present, Late, Absent, or Excused THEN the record updates to that status and an audit entry records actor, time, old value, new value, and reason
- WHEN demo seed data is loaded THEN the seeded class section includes a usable attendance policy (non-zero present and late windows) so Present vs Late can be exercised without admin UI

## Out of scope

- School / faculty / course policy hierarchy — section-level policy only for this slice
- Absence-threshold alerts, reports, and CSV/Excel export (Phase 2 remainder)
- GPS validation and Suspicious review flow
- Academic Admin (or other) roles and a full policy-management console beyond what seed + lecturer close/manual needs
- Manual-edit time limits and admin-approval gates for late edits
- Realtime dashboard polish beyond showing the new statuses where the lecturer already sees roster/manual UI

## Acceptance criteria

- [ ] Successful QR check-in inside the present window yields Present; after present but inside late yields Late
- [ ] Check-in after both windows are exceeded is rejected with a failed-attempt reason
- [ ] Closing attendance marks enrolled students with no successful record as Absent; already Present/Late/Manual Present/Excused students are left unchanged
- [ ] Lecturer can manually set Manual Present, Late, Absent, or Excused, each producing an audit entry with before/after and reason
- [ ] Seeded demo section ships with a policy that makes Present vs Late distinguishable in a demo run
