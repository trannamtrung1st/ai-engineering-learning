# Epic 5: Instructor Live Monitoring, Overrides & Export

Instructor monitors realtime attendance, corrects exceptions, and exports final reports.

### Story 5.1: Instructor Live Attendance Dashboard with Realtime

As an Instructor running an active workshop,
I want a live attendance table that updates automatically as students check in,
So that I can monitor who is present without refreshing the page.

**Acceptance Criteria:**

**Given** an **active** or **closed** workshop session with a bound roster and existing `attendance_records` / `check_in_attempts` from Epic 4
**When** the Instructor opens the live dashboard at `app/(instructor)/sessions/[id]/live/` (UX-DR21, UX-DR14)
**Then** the table lists all roster Students with columns: name, student_id, status, last reason, override action (UX-DR14)
**And** status values display as badge pills with text labels: Present (success), Absent (neutral), Failed (danger), Manual Override (warning) (UX-DR6)
**And** the table uses a 2px outer border, shadow-md, zebra rows, and sticky header (UX-DR8)
**When** a Student successfully checks in
**Then** their row updates via Supabase `postgres_changes` on `attendance_records` filtered by `session_id` without manual page refresh (FR14, AD-8)
**And** new check-ins appear within 5 seconds under 150 concurrent users (FR14, NFR1)
**And** header counts show present / total roster (FR14)
**And** a live indicator shows brand-filled square + caption "Đang cập nhật"; pulsing is suppressed when `prefers-reduced-motion` is set (UX-DR10, UX-DR25)
**And** skeleton rows render on initial load; live indicator is grey until first realtime event (UX-DR35)
**And** search/filter by name or student_id is available for 150-row rosters (UX-DR36)
**And** RLS ensures the Instructor sees only their own sessions (AD-8)

### Story 5.2: Manual Attendance Override with Required Reason

As an Instructor,
I want to manually mark a student Present or Absent with a required reason,
So that I can correct GPS failures and other exceptions while preserving an audit trail.

**Acceptance Criteria:**

**Given** an Instructor on the live dashboard for an **active** or **closed** session
**When** they open the Manual Override modal for a roster student (UX-DR15)
**And** they select Present or Absent and enter a non-empty reason in the required textarea
**Then** `api/src/domain/attendance/manual-override.ts` updates the `attendance_records` row and appends one `check_in_attempts` row with `source = manual` and `actor_id` set to the Instructor (FR15, AD-3, AD-11)
**When** they submit without a reason
**Then** the override is rejected with a validation error
**When** the override succeeds
**Then** the live table row updates to reflect the new status and Manual Override badge (FR15, UX-DR6)
**And** the override reason is stored and retrievable in audit history (FR15)
**And** writes go through NestJS API with `RolesGuard('instructor')`; web calls via `lib/api-client.ts`; clients never write domain tables directly (AD-3, AD-7, AD-15)

### Story 5.3: Session Attendance CSV Export

As an Instructor,
I want to download a CSV of attendance for a session,
So that I can archive results and share them after the workshop.

**Acceptance Criteria:**

**Given** an **active** or **closed** session with a bound roster
**When** the Instructor requests export via `GET {NEXT_PUBLIC_API_URL}/api/v1/sessions/:id/export.csv` with `RolesGuard('instructor')` (AD-7, AD-15)
**Then** `api/src/domain/export/exportSessionCsv` returns a CSV with one row per roster Student (FR18)
**And** columns include: `student_id`, `full_name`, `email`, `attendance_status`, `check_in_timestamp` (if present), `source` (`automated` | `manual_override`) (FR18)
**And** row count equals roster size including students who never checked in (FR18)
**When** a student was marked present via manual override
**Then** the `source` column shows `manual_override` (FR18, UJ-4)
**And** the download is available from session detail for active and closed sessions (UX-DR21)
