---
id: SPEC-hesd-workshop-attendance
companions:
  - check-in-validation.md
  - roles.md
  - architecture-diagrams.md
  - ../../project-context.md
sources:
  - ../../../raw/initial-idea.md
---

> **Canonical contract.** This SPEC and the files in `companions:` are the complete, preservation-validated contract for what to build, test, and validate. Source documents listed in frontmatter are for traceability only — consult them only if you need narrative rationale or prose color this contract intentionally omits.

# HESD Workshop Digital Attendance System

## Why

Manual roll call, paper sign-in, and list checks for HESD workshops (~100–150 students per cohort) waste organizer and instructor time, produce inaccurate attendance data, and make proxy check-ins easy. A digital attendance system lets organizers check students in quickly, keep reliable participation records, and export post-session reports — replacing a pain point with a fast, auditable mobile-web flow.

## Capabilities

- **CAP-1**
  - **intent:** Instructor can create and configure a workshop session, including geofence center and radius and roster binding.
  - **success:** A configured session appears in the system and is ready to activate for live check-in with its bound roster and location rules per `check-in-validation.md`.

- **CAP-2**
  - **intent:** System displays a dynamic QR code for an active session that rotates every 30 seconds.
  - **success:** While a session is active, the displayed QR encodes a valid session token and refreshes on a 30-second cadence; multiple students can scan the same token before expiry.

- **CAP-3**
  - **intent:** Student can check in via mobile web after scanning the session QR and signing in with an admin-provisioned account.
  - **success:** A signed-in student who scans a live session QR reaches the check-in flow and receives either a confirmed attendance result or a clear rejection reason.

- **CAP-4**
  - **intent:** System validates check-in against QR expiry, roster membership, prior check-in, and GPS geofence before recording attendance.
  - **success:** Attendance is recorded only when all validation checks in `check-in-validation.md` pass; any failed check leaves attendance unchanged and logs the attempt.

- **CAP-5**
  - **intent:** Instructor can view realtime attendance status for an active session.
  - **success:** During a live session, the instructor dashboard reflects new check-ins within observable realtime latency without manual refresh.

- **CAP-6**
  - **intent:** Instructor can manually mark or correct attendance when exceptions occur.
  - **success:** A manual attendance change is persisted, visible on the session dashboard, and distinguishable from automated check-ins in the audit log.

- **CAP-7**
  - **intent:** System records an audit log of check-in attempts including failed and anomalous attempts.
  - **success:** Every check-in attempt (success or failure) is retrievable with student identity, timestamp, outcome, and failure reason where applicable.

- **CAP-8**
  - **intent:** Admin can manage workshop rosters via manual entry or CSV import.
  - **success:** Roster students can be added, updated, or removed by either method, and roster membership is enforced during session check-in.

- **CAP-9**
  - **intent:** Instructor can export session attendance as CSV after the workshop.
  - **success:** Exported CSV contains one row per roster student with final attendance status for the session and opens correctly in standard spreadsheet tools.

- **CAP-10**
  - **intent:** Admin can provision student accounts manually or via CSV bulk import.
  - **success:** Provisioned students can sign in and attempt check-in; bulk CSV import creates or updates accounts in one operation with per-row error reporting.

## Constraints

- Pilot scale: **100–150 students** per workshop cohort.
- Check-in channel is **mobile web**; native mobile apps are out of scope for the pilot.
- **Login is required** before a check-in can complete; accounts are **admin-provisioned only** (no self-registration in MVP).
- QR tokens are **short-lived multi-use session tokens** (30-second lifetime); see `check-in-validation.md`.
- **One successful check-in per student per workshop session** — enforced at the student level, not the token level.
- GPS geofence is a **circular radius** (default 100 m, configurable 50–200 m per session); see `check-in-validation.md`.
- **Admin and instructor are distinct roles** with separate surfaces; see `roles.md`.
- Fraud reduction uses **layered checks**, not absolute anti-fraud; manual fallback remains available.
- UI follows the **Neobrutalism design system** (`../../project-context.md` routes to `docs/ui-ux/design-system/`).
- Implementation stack is **not yet selected**; this spec is stack-agnostic.

## Non-goals

- School SSO integration
- Academic affairs / registrar system integration
- School-wide attendance policy enforcement
- Face recognition or biometric verification
- Native mobile app (iOS/Android)
- Student self-registration

## Success signal

During a live HESD workshop with ~100–150 students, an admin has provisioned accounts and rosters, an instructor activates a session with geofence configured, students check in via mobile web within minutes using the rotating QR, the instructor sees attendance update in realtime, exceptions are handled manually when needed, and a complete attendance CSV is exported after the session — with audit logs available for any disputed check-ins.

## Assumptions

- Documentation and spec output are in **English** per project configuration, though the source idea was authored in Vietnamese.
- **Pilot scope only** — advanced integrations and enterprise features are explicitly deferred.
- Student devices have **GPS capability and permission** available in the mobile browser during check-in.
