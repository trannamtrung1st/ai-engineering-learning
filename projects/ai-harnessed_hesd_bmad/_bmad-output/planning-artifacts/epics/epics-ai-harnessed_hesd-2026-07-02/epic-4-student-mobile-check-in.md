# Epic 4: Student Mobile Check-In

Students scan QR and complete validated, GPS-enforced check-in with clear Vietnamese outcomes.

### Story 4.1: Student QR Deep-Link Entry and Session Gate

As a Student,
I want scanning the workshop QR to open the correct check-in page for that session,
So that I can start check-in without manually finding or selecting a session.

**Acceptance Criteria:**

**Given** a QR code encoding a URL to `app/(student)/check-in/` with `sessionId` and `token` query parameters (AD-4, UX-DR37)
**When** the Student opens the URL on mobile web (OS camera app — no in-app scanner)
**Then** the route resolves session context from `sessionId` without manual session selection (FR11)
**When** the session is **active**
**Then** the page proceeds to sign-in (if unauthenticated) or the check-in form (if already signed in as a Student)
**When** the session is **draft** or **scheduled**
**Then** a Vietnamese message explains the session is not open yet and check-in is blocked before login (FR11, UX-DR31)
**When** the session is **closed**
**Then** a Vietnamese closed-session message is shown and check-in is blocked before login (FR11, UX-DR31)
**And** the layout is mobile-first single column with safe-area padding for notched phones (UX-DR26)
**And** unauthenticated Students are redirected to sign-in with return URL preserving `sessionId` and `token` (UX-DR22)

### Story 4.2: Check-In Validation Orchestrator, Schema, and API

As a Student submitting a check-in,
I want the system to validate my attempt in a strict, atomic order,
So that attendance is recorded only when all rules pass and every attempt is audited.

**Acceptance Criteria:**

**Given** migrations for `attendance_records` (`session_id`, `student_id`, `status`, `checked_in_at`, `source`) and append-only `check_in_attempts` (`student_id`, `session_id`, `outcome`, `failure_reason`, `lat`, `lng`, `source`, `actor_id`, `timestamp`)
**When** `executeCheckIn(input)` in `api/src/domain/check-in/` is invoked via `POST /api/v1/check-in`
**And** `AuthGuard` validates Supabase JWT and `RolesGuard` enforces student role (AD-3, AD-5, AD-15)
**Then** checks run **in order** inside one DB transaction: (1) authenticated student, (2) valid unexpired token for session, (3) roster membership, (4) no prior successful check-in, (5) GPS within geofence (FR12, check-in-validation.md)
**When** any check fails
**Then** no attendance record is created, one `check_in_attempts` row is appended with outcome and `failure_reason`, and a typed rejection reason is returned (FR12, FR16, AD-11)
**When** all checks pass
**Then** an `attendance_records` row is upserted with status Present and `source = automated`, and a success `check_in_attempts` row is appended (FR12, FR16)
**And** a unique constraint on `attendance_records(session_id, student_id)` where `status = checked_in` prevents race-condition duplicates (AD-6, NFR1)
**And** the client sends `{ lat, lng, accuracyM }`; server computes haversine distance and passes if `distance <= session.radius_m` (AD-10)
**And** raw GPS coordinates are stored in `check_in_attempts` **only on failure**; never exposed to other students (AD-10, NFR6)
**And** domain writes use Drizzle in `api/` only; web clients never insert directly on domain tables (AD-3, AD-13)

### Story 4.3: Student Mobile Check-In UI with GPS and Vietnamese Outcomes

As a Student at an active workshop,
I want to grant GPS permission, tap check-in, and see a clear Vietnamese result,
So that I know immediately whether I am marked present and what to do if something fails.

**Acceptance Criteria:**

**Given** a signed-in Student (password change gate already satisfied per Story 1.4) on the active-session check-in page with a valid `token` in the URL
**When** the page loads
**Then** a plain-language Vietnamese GPS permission prompt explains why location is needed (UX-DR22)
**And** the primary CTA **Điểm danh** is disabled until GPS resolves or a GPS error is shown (UX-DR18)
**When** GPS permission is denied
**Then** a GPS denied error panel shows steps to enable location; the attempt is not submitted; guidance matches `gps_denied` copy (UX-DR32, UX-DR29)
**When** the Student taps **Điểm danh** with GPS resolved
**Then** the client calls `POST {NEXT_PUBLIC_API_URL}/api/v1/check-in` via `lib/api-client.ts` with `sessionId`, `token`, and `{ lat, lng, accuracyM }`
**When** check-in succeeds
**Then** a success Card shows session title, check-in timestamp, and Present status badge with text label (FR13, UX-DR4, UX-DR6, UX-DR29)
**When** check-in fails
**Then** a failure Card shows the Vietnamese reason and one actionable recovery step for each code: `gps_denied`, `gps_out_of_range`, `already_checked_in`, `not_on_roster`, `token_expired` (FR13, UX-DR29)
**And** all form fields and errors meet WCAG 2.1 AA — labeled fields, `aria-describedby` on errors, focus order headline → body → CTA, tap targets ≥ 48px (UX-DR23, NFR4)
**And** the primary button is full-width with min height 48px per design tokens (UX-DR2, UX-DR26)
**And** check-in works on current Chrome and Safari on iOS and Android (NFR3)
