# 3. Glossary

- **Admin** — Role with access to Admin web pages: account provisioning, roster management, audit log review. Does not operate live Workshop Sessions.
- **Attendance Record** — Final per-student attendance state for one Workshop Session (Present, Absent, or Manual Override).
- **Audit Log Entry** — Immutable record of a check-in attempt or manual override (actor, timestamp, outcome, reason).
- **Check-In Attempt** — One student submission against an Active Workshop Session; may succeed or fail validation.
- **Cohort Roster** — Named list of Students eligible for workshop attendance; managed by Admin.
- **Geofence** — Circular GPS boundary (center lat/lng + radius meters) attached to a Workshop Session.
- **Instructor** — Role with access to Instructor web pages: session lifecycle, QR Display, realtime dashboard, manual override, CSV export.
- **Manual Override** — Instructor action that sets or changes an Attendance Record with a required reason; distinguished in Audit Log from automated check-in.
- **QR Display** — Full-screen Instructor view showing the rotating QR for projection.
- **Session Token** — Short-lived multi-use token encoded in the QR; 30-second lifetime; bound to one Active Workshop Session.
- **Student** — Role that signs in on mobile web and performs Check-In Attempts.
- **Workshop Session** — One attendable instance of an HESD workshop block with lifecycle state, bound Cohort Roster, Geofence, and Attendance Records.
