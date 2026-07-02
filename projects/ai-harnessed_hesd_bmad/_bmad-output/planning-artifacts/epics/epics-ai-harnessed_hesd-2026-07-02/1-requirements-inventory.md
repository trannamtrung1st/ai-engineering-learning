# Requirements Inventory

### Functional Requirements

FR1: Admin provisions Student accounts manually with student_id, full_name, email, and optional initial password; duplicate student_id or email is rejected with a clear error; created Student can sign in on mobile web.
FR2: Admin bulk-provisions Student accounts via CSV (columns: student_id, full_name, email, optional initial_password); import returns per-row success/failure summary; rows without initial_password receive a system-generated temporary password shown once in the import result.
FR3: Admin, Instructor, and Student can sign in only to surfaces permitted for their role; Student credentials cannot access Admin or Instructor dashboards; Instructor cannot access Admin-only pages.
FR3a: Student signing in with an admin-set or system-generated initial password is prompted to set a new password before accessing check-in; check-in flow is blocked until password change completes; password change is recorded in Audit Log Entry (no password value stored).
FR4: Admin can create Instructor accounts (email, display name); new Instructor can sign in to Instructor dashboard; Instructor cannot provision Student accounts.
FR5: Admin can add, edit, or remove Students on a named Cohort Roster by student_id; student_id must reference an existing Student account; removed student is no longer eligible for new check-ins on sessions bound to that roster.
FR6: Admin can upload CSV with student_id and optional cohort_label to bulk add Students to a roster; import mode is append (default) or replace entire roster (explicit admin choice before upload); unknown student_id rows fail with per-row errors; replace mode removes roster members not present in the CSV after successful import.
FR7: Instructor can create a Workshop Session with title, scheduled date/time, and bound Cohort Roster; new session starts in draft state; session cannot activate without a bound roster and Geofence.
FR8: Instructor can set Geofence center (map pin or current location) and radius (50–200 m; default 100 m); saved Geofence is used for all Check-In Attempts on that session.
FR9: Instructor can transition session lifecycle: draft → scheduled → active → closed; QR Display is available only in active state; Check-In Attempts accepted only in active state; closed sessions reject new check-ins (existing Attendance Records read-only except via FR15).
FR10: System rotates Session Token every 30 seconds in QR Display for Active Workshop Session; token remains valid for 30 seconds from issuance; multiple Students can use the same token before expiry; expired token rejects check-in with reason token_expired.
FR11: Student scanning QR on mobile opens the check-in flow for the correct Workshop Session via deep link; inactive or closed session shows appropriate error before login.
FR12: System validates Check-In Attempts in order: authenticated Student → valid Session Token → on roster → not already checked in → inside Geofence; failure at any step rejects attendance and logs Audit Log Entry with failure reason; success creates Attendance Record Present with automated source tag.
FR13: Student sees explicit success or failure message with reason codes displayed in Vietnamese; success shows session title and check-in timestamp; failure shows actionable guidance for gps_denied, gps_out_of_range, already_checked_in, not_on_roster, token_expired.
FR14: Instructor views live attendance table listing all roster Students with status Present, Absent, Failed (last attempt reason), or Manual Override; new successful check-ins appear without manual page refresh within 5 seconds under 150 concurrent users; counts show present / total roster.
FR15: Instructor can mark a Student Present or Absent on an Active or Closed session with a required text reason; override updates Attendance Record and creates Audit Log Entry tagged manual_override; override reason is visible in audit history.
FR16: System logs every Check-In Attempt with student_id, session_id, timestamp, outcome, and failure reason when applicable; successful and failed attempts are retrievable; logs are append-only from UI (no delete/edit).
FR17: Admin can filter Audit Log Entries by session, student, date range, and outcome; Admin view is read-only; export of raw audit log is non-goal for MVP (browse in UI only).
FR18: Instructor can download CSV for a Closed (or Active) session with one row per roster Student; columns include student_id, full_name, email, attendance_status, check_in_timestamp (if present), source (automated | manual_override); row count equals roster size.

### NonFunctional Requirements

NFR1: System supports at least 150 Check-In Attempts within a 10-minute window per Active session without degrading below FR14 latency target (5-second dashboard update).
NFR2: 99% uptime during scheduled HESD workshop hours for pilot term.
NFR3: Student check-in works on current versions of Chrome and Safari on iOS and Android.
NFR4: Student check-in flow meets WCAG 2.1 AA for forms, errors, and success states.
NFR5: Attendance Records and Audit Log Entries retained minimum 90 days from session date.
NFR6: GPS coordinates used only for Geofence validation at check-in time; raw coordinates stored in Audit Log Entry for failed attempts only; not displayed to other Students.

### Additional Requirements

- **Starter template (Epic 1 Story 1):** Bootstrap web with `npx create-next-app -e with-supabase`; keep `@supabase/ssr` cookie auth and `middleware.ts` session refresh from template. Story 1.1b adds NestJS API + Docker Compose.
- **Stack:** Next.js 16.2.9 web + NestJS 11.1.27 API (`api/`), Node.js 20+, TypeScript 5.x, Tailwind CSS 4.x, Supabase (Postgres + Auth + Realtime), Drizzle ORM 0.45.2 in API only, Docker Compose v2 (profiles local + integration).
- **AD-1:** Split-stack monorepo — web role surfaces under `app/(admin)/`, `app/(instructor)/`, `app/(student)/`; domain logic only in `api/src/domain/`.
- **AD-3:** All writes to attendance_records, check_in_attempts, session_tokens, rosters, and accounts go through NestJS controllers → `api/src/domain/` use-cases; web calls API with Supabase JWT; clients never call Drizzle or Supabase insert/update/delete on domain tables.
- **AD-4:** `mintSessionToken(sessionId)` runs in NestJS API only; token stored with expires_at = now() + 30s; QR encodes URL to student check-in route; Instructor QR display polls `GET {API_URL}/api/v1/sessions/:id/qr-token` every ≤5s.
- **AD-5:** Single entry `executeCheckIn(input)` in `api/src/domain/check-in/` runs validation checks in order inside one DB transaction; on failure rollback attendance and append audit row; on success upsert attendance_records and append audit row.
- **AD-6:** DB unique constraint on `attendance_records(session_id, student_id)` where status = checked_in as backstop against race-condition duplicate check-ins.
- **AD-7:** `profiles.role` enum admin | instructor | student; web middleware guards route prefixes by role; NestJS `AuthGuard` + `RolesGuard` on every controller; Supabase RLS mirrors role rules on reads.
- **AD-8:** Instructor live session view subscribes to Supabase `postgres_changes` on `attendance_records` filtered by session_id; no custom WebSocket server.
- **AD-9:** Remove/disable template public sign-up route; Admin creates users via Supabase Auth Admin API (service_role key, server-only); first-login password change enforced in middleware for students with must_change_password = true.
- **AD-10:** Student client sends { lat, lng, accuracyM } with check-in attempt; server computes haversine distance to session center; pass if distance <= session.radius_m; store raw coords in check_in_attempts only on failure.
- **AD-11:** Table `check_in_attempts` is append-only; every path through executeCheckIn and manual override writes one row with outcome, failure_reason, lat/lng (on failure), source (auto|manual), actor_id; no updates/deletes in MVP.
- **AD-12:** Local: `docker compose --profile local` (Postgres + API per AD-14) + `supabase start` or remote dev for Auth/Realtime; production: Vercel (web) + Supabase hosted; API host TBD; bootstrap admin via `supabase/seed.sql`; secrets API-only.
- **AD-13:** Domain writes use Drizzle in `api/` with server-only DATABASE_URL; API resolves actor { id, role } from JWT + profile; web reads via Supabase client (RLS); web never holds DATABASE_URL.
- **AD-14:** Docker Compose at repo root — profile `local` (postgres + api), profile `integration` (migrate/seed for CI).
- **AD-15:** NestJS 11.1.27 in `api/`; modules by bounded context; global AuthGuard + RolesGuard.
- **Database schema:** Drizzle schema + migrations in `api/` for profiles, cohort_rosters, roster_members, workshop_sessions, session_tokens, attendance_records, check_in_attempts per structural seed.
- **API surface:** NestJS `/api/v1/` — GET `/sessions/:id/qr-token` (instructor), POST `/check-in` (student), POST `/admin/accounts` (admin), POST `/admin/rosters/:id/import` (admin), GET `/sessions/:id/export.csv` (instructor); web calls via `lib/api-client.ts`.
- **Environment variables:** NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY, NEXT_PUBLIC_API_URL (web); SUPABASE_SERVICE_ROLE_KEY, DATABASE_URL, SUPABASE_JWT_SECRET (api only).
- **Build order:** Phase 0 (api + compose) → phases 1–10 (schema → auth → admin accounts → rosters → sessions → QR → check-in → live dashboard → override/audit → CSV export).
- **Security constraints:** Passwords stored hashed; Session Tokens server-validated; initial Admin account seeded via deployment setup; student location collected only during Check-In Attempts, not tracked continuously.
- **Pilot scale:** 100–150 students per workshop cohort; mobile web only (no native apps); admin-provisioned accounts only (no self-registration).

### UX Design Requirements

UX-DR1: Implement Neobrutalism design tokens from DESIGN spine YAML (colors, typography, spacing, rounded) as CSS/Tailwind theme foundation; load `docs/ui-ux/design-system/` module files via neobrutalism-design-system skill before UI implementation.
UX-DR2: Primary button component — brand background, 2px border, 3px shadow offset, min height 48px, full-width on student mobile.
UX-DR3: Danger button component — danger background, white foreground, for end session and destructive roster replace actions.
UX-DR4: Card component — 2px border, 4px shadow offset, for session summary, import result panels, check-in success/failure panels.
UX-DR5: Input/select component — 2px border, 3px focus border, danger left border accent on error state.
UX-DR6: Attendance status badge pills — Present (success), Absent (neutral), Failed (danger), Manual Override (warning); always paired with text label (not color-only).
UX-DR7: QR Display frame — 3px border, 10px shadow offset, session title above QR, countdown below using qr-countdown typography token, "HESD Workshop" meta label.
UX-DR8: Data table — 2px outer border, shadow-md, zebra rows via neutral-secondary alternating, sticky header on Instructor dashboard.
UX-DR9: CSV upload zone — dashed 2px border, brand background on drag-over.
UX-DR10: Live indicator — brand-filled square + caption "Đang cập nhật"; suppress pulsing dot when prefers-reduced-motion is set.
UX-DR11: Session lifecycle stepper — four states (draft, scheduled, active, closed); only Active enables QR + check-in; Closed locks new check-ins.
UX-DR12: Geofence map — pin drag + radius slider 50–200m (default 100m); "Use my location" sets pin.
UX-DR13: QR Display — auto-refresh token every 30s with visible countdown; ESC exits to session detail; supports browser full-screen (F11) for projector mode.
UX-DR14: Live attendance table — columns: name, student_id, status, last reason, override action; sticky header; auto-refresh via realtime subscription.
UX-DR15: Manual override modal — status toggle + required reason textarea; confirm applies immediately.
UX-DR16: CSV import panel — template download link, file picker, per-row success/fail summary table.
UX-DR17: Roster import mode — radio Append vs Replace; must choose before upload.
UX-DR18: Student check-in CTA — single primary button; disabled until GPS resolved or error shown.
UX-DR19: Audit log filters — session, student, date range, outcome; paginated 50 rows/page.
UX-DR20: Admin web IA — dashboard (counts + quick links), Students list/create/CSV import, Instructors list/create, Rosters list/detail/CSV import, Audit log browse; Admin does not operate live Workshop Sessions.
UX-DR21: Instructor web IA — dashboard (upcoming/active/past sessions), session create/edit, lifecycle controls, QR Display, live attendance dashboard, manual override row action, CSV export.
UX-DR22: Student mobile web IA — QR scan deep link entry, sign-in, first-login password change gate, GPS permission prompt with plain-language why, Vietnamese check-in outcome screen.
UX-DR23: WCAG 2.1 AA for student check-in — all form fields labeled, errors associated with aria-describedby, focus order headline → body → CTA, tap targets ≥ 48px.
UX-DR24: QR Display minimum 4.5:1 contrast on session title and countdown; no hover-only controls on QR surface.
UX-DR25: prefers-reduced-motion — disable live-indicator pulse; instant QR swap without animation.
UX-DR26: Student mobile-first single column layout with safe-area padding for notched phones.
UX-DR27: Instructor/Admin sidebar nav at ≥768px; collapsible nav drawer below 768px.
UX-DR28: QR Display scales QR to max 70vh; typography uses display-mobile minimum on small projectors.
UX-DR29: Vietnamese microcopy for all student-facing outcomes and failure reason codes (gps_denied, gps_out_of_range, already_checked_in, not_on_roster, token_expired).
UX-DR30: English admin import error messages with row-level detail (e.g., "3 rows failed — duplicate email in row 12").
UX-DR31: Session state banners — draft yellow banner "Chưa sẵn sàng — cần gắn danh sách và vùng GPS"; closed session message on student link; empty roster blocks activation with link to contact Admin.
UX-DR32: GPS denied error panel with steps to enable location; attempt logged.
UX-DR33: First-login password full-screen gate before check-in form.
UX-DR34: Import partial failure UI — keep successful rows, highlight failures, allow re-upload of fixed CSV.
UX-DR35: Dashboard skeleton rows on load; live indicator grey until first realtime poll.
UX-DR36: Instructor live table search/filter by name or student_id for 150-row rosters (no infinite scroll without filter).
UX-DR37: Camera QR scan is out of app — OS camera app opens URL; no in-app QR scanning.

### FR Coverage Map

FR1: Epic 2 - Admin manual student provisioning
FR2: Epic 2 - Admin CSV bulk student provisioning
FR3: Epic 1 - Role-based sign-in to permitted surfaces
FR3a: Epic 1 - Student first-login password change gate
FR4: Epic 2 - Admin instructor account management
FR5: Epic 2 - Admin manual roster management
FR6: Epic 2 - Admin CSV roster import (append/replace)
FR7: Epic 3 - Instructor creates workshop session
FR8: Epic 3 - Instructor configures geofence
FR9: Epic 3 - Instructor session lifecycle control
FR10: Epic 3 - 30-second rotating Session Token QR display
FR11: Epic 4 - Student QR deep-link check-in entry
FR12: Epic 4 - Ordered check-in validation orchestrator
FR13: Epic 4 - Vietnamese success/failure outcomes
FR14: Epic 5 - Instructor live attendance dashboard
FR15: Epic 5 - Manual attendance override with reason
FR16: Epic 4 (+ Epic 5) - Append-only audit logging (check-in + override paths)
FR17: Epic 6 - Admin audit log browse/filter
FR18: Epic 5 - Instructor session CSV export
