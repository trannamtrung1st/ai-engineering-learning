# 4. Features

## 4.1 Identity and Access

**Description:** Admins provision Student accounts; Admins and Instructors authenticate to web dashboards; Students authenticate on mobile web. No self-registration. Realizes UJ-1, UJ-3.

### FR-1: Admin provisions Student accounts manually

Admin can create a Student account with student_id, full_name, email, and optional initial password.

**Consequences (testable):**
- Duplicate student_id or email is rejected with a clear error.
- Created Student can sign in on mobile web with email and password.

### FR-2: Admin bulk-provisions Student accounts via CSV

Admin can upload a CSV with columns `student_id`, `full_name`, `email`, optional `initial_password` to create or update accounts in one operation.

**Consequences (testable):**
- Import returns per-row success/failure summary; valid rows persist.
- Rows without `initial_password` receive a system-generated temporary password shown once in the import result.

### FR-3: Role-based sign-in

Admin, Instructor, and Student can sign in only to surfaces permitted for their role.

**Consequences (testable):**
- Student credentials cannot access Admin or Instructor dashboards.
- Instructor cannot access Admin-only pages (account provisioning, global audit).

### FR-4: Admin manages Instructor accounts

Admin can create Instructor accounts (email, display name) for workshop facilitators.

**Consequences (testable):**
- New Instructor can sign in to Instructor dashboard.
- Instructor cannot provision Student accounts.

### FR-3a: Student must change password on first login

Student signing in with an admin-set or system-generated initial password is prompted to set a new password before accessing check-in.

**Consequences (testable):**
- Check-in flow is blocked until password change completes.
- Password change is recorded in Audit Log Entry (no password value stored).

---

## 4.2 Roster Management

**Description:** Admin maintains Cohort Rosters used when binding Workshop Sessions. Realizes UJ-1.

### FR-5: Admin manages roster manually

Admin can add, edit, or remove Students on a named Cohort Roster by student_id.

**Consequences (testable):**
- student_id must reference an existing Student account.
- Removed student is no longer eligible for new check-ins on sessions bound to that roster.

### FR-6: Admin imports roster via CSV

Admin can upload CSV with `student_id` and optional `cohort_label` to bulk add Students to a roster. Import mode is **append** (default) or **replace entire roster** (explicit admin choice before upload).

**Consequences (testable):**
- Unknown student_id rows fail with per-row errors; valid rows are added.
- **Replace** mode removes roster members not present in the CSV after successful import.
- **Append** mode leaves existing members unchanged.

---

## 4.3 Workshop Session Management

**Description:** Instructor creates and configures Workshop Sessions, binds a Cohort Roster, sets Geofence, and drives lifecycle. Realizes UJ-2.

### FR-7: Instructor creates a Workshop Session

Instructor can create a session with title, scheduled date/time, and bound Cohort Roster.

**Consequences (testable):**
- New session starts in **draft** state.
- Session cannot activate without a bound roster and Geofence.

### FR-8: Instructor configures Geofence

Instructor can set Geofence center (map pin or current location) and radius (50–200 m; default 100 m).

**Consequences (testable):**
- Default radius is 100 m when not specified.
- Saved Geofence is used for all Check-In Attempts on that session.

### FR-9: Instructor controls session lifecycle

Instructor can transition session: **draft** → **scheduled** → **active** → **closed**.

**Consequences (testable):**
- QR Display is available only in **active** state.
- Check-In Attempts accepted only in **active** state.
- **closed** sessions reject new check-ins; existing Attendance Records are read-only except via FR-15.

---

## 4.4 Dynamic QR Display

**Description:** While Active, system shows a rotating QR encoding a valid Session Token. Realizes UJ-2, CAP-2.

### FR-10: System rotates Session Token every 30 seconds

In QR Display, the encoded Session Token refreshes on a 30-second cadence for the Active Workshop Session.

**Consequences (testable):**
- Token remains valid for 30 seconds from issuance.
- Multiple Students can use the same token before expiry.
- Expired token rejects check-in with reason `token_expired`.

---

## 4.5 Student Check-In (Mobile Web)

**Description:** Student scans QR, signs in if needed, submits Check-In Attempt; system runs validation sequence. Realizes UJ-3, CAP-3, CAP-4.

### FR-11: Student opens check-in from QR scan

Scanning the QR on mobile opens the check-in flow for the correct Workshop Session.

**Consequences (testable):**
- Deep link resolves to session context without manual session selection.
- Inactive or closed session shows appropriate error before login.

### FR-12: System validates Check-In Attempts in order

System evaluates: authenticated Student → valid Session Token → on roster → not already checked in → inside Geofence.

**Consequences (testable):**
- Failure at any step rejects attendance and logs Audit Log Entry with failure reason.
- Success creates Attendance Record Present with automated source tag.

### FR-13: Student receives clear check-in outcome

Student sees explicit success or failure message with reason codes displayed in Vietnamese.

**Consequences (testable):**
- Success shows session title and check-in timestamp.
- Failure shows actionable guidance for `gps_denied`, `gps_out_of_range`, `already_checked_in`, `not_on_roster`, `token_expired`.

---

## 4.6 Realtime Attendance Dashboard

**Description:** Instructor monitors roster attendance during Active session. Realizes UJ-2, UJ-4, CAP-5.

### FR-14: Instructor views live attendance table

Dashboard lists all roster Students with status: Present, Absent, Failed (last attempt reason), or Manual Override.

**Consequences (testable):**
- New successful check-ins appear without manual page refresh within 5 seconds under 150 concurrent users.
- Counts show present / total roster.

---

## 4.7 Manual Attendance Override

**Description:** Instructor corrects exceptions with audit trail. Realizes UJ-4, CAP-6.

### FR-15: Instructor manually sets attendance

Instructor can mark a Student Present or Absent on an Active or Closed session with a required text reason.

**Consequences (testable):**
- Override updates Attendance Record and creates Audit Log Entry tagged `manual_override`.
- Override reason is visible in audit history.

---

## 4.8 Audit Log

**Description:** System records all Check-In Attempts and overrides. Admin reviews globally; Instructor sees session-scoped entries. Realizes UJ-5, CAP-7.

### FR-16: System logs every Check-In Attempt

Each attempt records student_id, session_id, timestamp, outcome, and failure reason when applicable.

**Consequences (testable):**
- Successful and failed attempts are retrievable.
- Logs are append-only from UI (no delete/edit).

### FR-17: Admin browses audit logs

Admin can filter Audit Log Entries by session, student, date range, and outcome.

**Consequences (testable):**
- Admin view is read-only.
- Export of raw audit log is `[NON-GOAL for MVP]` — browse in UI only.

---

## 4.9 Attendance Export

**Description:** Instructor exports final attendance after session. Realizes UJ-4, CAP-9.

### FR-18: Instructor exports session CSV

Instructor can download CSV for a Closed (or Active) session with one row per roster Student.

**Consequences (testable):**
- Columns include: student_id, full_name, email, attendance_status, check_in_timestamp (if present), source (automated | manual_override).
- Row count equals roster size.

---

## 4.10 Information Architecture

**Description:** Three surfaces in MVP. UI follows Neobrutalism design tokens per `docs/ui-ux/design-system/`.

| Surface | Primary role | Device |
|---------|--------------|--------|
| Admin web app | Admin | Desktop / tablet |
| Instructor web app | Instructor | Desktop / tablet (+ projector for QR Display) |
| Mobile web check-in | Student | Phone |

Admin and Instructor share a single web codebase with role-gated routes.

---
