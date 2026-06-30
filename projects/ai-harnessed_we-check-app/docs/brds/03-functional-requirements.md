# We Check — Functional Requirements

Implementable functional requirements (`FR-xx`) for **We Check** MVP. Each requirement specifies actor, behavior, inputs, outputs, and traceability to business workflows and capabilities defined in [prompt.md](./prompt.md) and [01-stakeholders-scope.md](./01-stakeholders-scope.md).

**Related documents:** [Business workflow](./02-business-workflow.md) · [Business rules](./04-business-rules.md) · [State machine](./05-state-machine.md) · [Domain model](./06-domain-model.md) · [Acceptance criteria](./08-acceptance-mvp-future.md)

---

## 1. Functional Requirements Overview

| ID range | Capability area | MVP priority |
| --- | --- | --- |
| FR-01 – FR-03 | Identity, authentication, roster (incl. manual class/subject) | Must |
| FR-04 – FR-05 | Session creation and lifecycle | Must |
| FR-06 – FR-09 | QR check-in, GPS, anti-fraud | Must |
| FR-10 – FR-11 | Student history and manual corrections | Must |
| FR-12 – FR-13 | Reporting and CSV export | Must |
| FR-14 – FR-16 | Should-capability enhancements | Should |
| FR-17 – FR-18 | Bootstrap, permission-gated nav, role hubs, chrome-less route discovery | Must |

Business rules (`BR-xx`) refine enforcement; acceptance tests (`AC-xx`) are defined in [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).

---

## 2. Functional Requirements

### FR-01 — User account provisioning

| Field | Specification |
| --- | --- |
| **Actor** | `TrainingOfficeAdmin` |
| **Behavior** | Admin creates, updates, and deactivates user accounts for students and instructors. Each account has a unique institutional identifier (student ID or staff ID) matching VAL-05 (`^[A-Za-z0-9\-_.]{3,32}$` — letters, digits, hyphen, underscore, period), display name, email, role assignment, and active flag. Deactivated users cannot log in or check in. |
| **Inputs** | User profile fields; role (`Student`, `Instructor`, `TrainingOfficeAdmin`); bulk CSV upload via `POST /users/import` (see below) |
| **Outputs** | Persisted user record; validation errors for duplicate IDs or invalid email; async import batch summary for CSV |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §3.1; capability: roster management baseline |

**Bulk CSV import (`POST /users/import`):** Admin bulk-imports user accounts for large cohorts (1000+ rows). Match key = `institutional_id` (mã SV / mã cán bộ). Required CSV columns: `institutional_id`, `display_name`, `email`, `role`, `active`. **Upsert semantics:**

- **Create** when ID not found: persist `display_name`, `email`, `role`, `active`; generate random initial password (not returned in import summary); `active` defaults `true` if column omitted.
- **Update** when ID exists: update `display_name`, `email`, `role`, `active` from row; **do not** change password or revoke sessions.
- **Reject row** on: invalid VAL-05, invalid email, invalid role enum, duplicate email belonging to a different `institutional_id`, malformed CSV row.

Outputs async import batch with accepted/rejected counts and row-level `errorDetails` (mirror roster import UX). Same file limits as VAL-12 (5 MB CSV, UTF-8). See [05-api-design.md](../technical/05-api-design.md) §3.2a and [AC-01d](./08-acceptance-mvp-future.md).

### FR-02 — Authentication before check-in

| Field | Specification |
| --- | --- |
| **Actor** | `Student`, `Instructor`, `TrainingOfficeAdmin` |
| **Behavior** | System requires a valid authenticated session before any check-in submission or protected report action. Unauthenticated users attempting check-in are redirected to the login page. After successful login, the user returns to the intended check-in flow. Session expires after configurable inactivity (default 8 hours). Authenticated users end their session via the header **UserMenu** on all role shells (Student, Instructor, Admin). Logout calls `POST /auth/logout`, revokes the server session, clears the HTTP-only cookie, and redirects to `/login` (no `returnUrl`). UserMenu shows read-only identity from `GET /auth/me`: `displayName`, `email`, `institutionalId`, and localized role label. |
| **Inputs** | Email (or institutional username) and password; logout action via UserMenu |
| **Outputs** | Auth session token; redirect to original URL on login success; localized error on failure; revoked session and login redirect on logout success |
| **Traceability** | [BR-06](./04-business-rules.md); workflow: [02-business-workflow.md](./02-business-workflow.md) §4.2 step 2 |

### FR-03 — Roster import and maintenance

| Field | Specification |
| --- | --- |
| **Actor** | `TrainingOfficeAdmin`, `Instructor` (read-only roster view) |
| **Behavior** | Admin imports class rosters via CSV when academic API is unavailable. Required columns: student ID, full name, class code, subject code. System validates format, rejects duplicate student IDs within a class, and surfaces row-level errors without partial silent failure. Roster import links enrollments to existing users by `institutional_id`; if user missing, creates student with synthetic email and random password (prefer bulk user CSV import first for large cohorts). When user exists, roster import updates `display_name` only — not email, role, password, or `active`. Instructor views enrolled students for assigned classes only. **Independent reference catalogs:** `Class` and `Subject` are separate entities — not paired 1:1. Many classes may share one subject (e.g. `HESD-01/SWE-101` and `HESD-02/SWE-101`); one class may have many subjects via distinct enrollment rows (e.g. same cohort in `SWE-101` and `SWE-102`). Linkage is many-to-many through `Enrollment(student, class, subject)`. **MVP admin surfaces:** Class catalog at `/admin/classes` (list + create); subject catalog at `/admin/subjects` (list + create). Roster CSV import references existing catalog codes. Codes are unique per entity, uppercase alphanumeric plus hyphen, max lengths per [08-validation-rules.md](../technical/08-validation-rules.md). Duplicate code → validation error. MVP: create-only — no edit/delete; cannot delete class with active enrollments. |
| **Inputs** | CSV file; class and subject identifiers; `ClassForm` and `SubjectForm` fields |
| **Outputs** | Enrollment records linked to students; import summary (accepted, rejected rows); persisted `Class` and `Subject` reference records visible on catalog list pages |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §3.0–§3.1; [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.1.1; catalog list pages per [14-listing-pages-search-filter-sort.md](../ui-ux/14-listing-pages-search-filter-sort.md) §0 |

### FR-04 — Session creation with room GPS

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor` |
| **Behavior** | Instructor creates a session in `Draft` state with class, subject, scheduled start time, session title, room name, room GPS coordinates (latitude/longitude), and optional GPS radius override (default **100 m**). System rejects activation without valid coordinates. Instructor may cancel a `Draft` session (`Cancelled` terminal state). |
| **Inputs** | Class, subject, schedule, room label, latitude, longitude, optional radius (meters) |
| **Outputs** | Session record in `Draft`; validation error if coordinates missing or out of valid range |
| **Traceability** | [BR-07](./04-business-rules.md); [05-state-machine.md](./05-state-machine.md) session lifecycle |

### FR-05 — Open, monitor, and close live session

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor` |
| **Behavior** | Instructor transitions session `Draft` → `Active` to start the attendance window and QR issuance. While `Active`, instructor views enrolled count and check-in progress. Instructor transitions `Active` → `Closed` to end check-in. System auto-closes attendance window **10 minutes** after scheduled start if instructor does not close manually. On close, all `Pending` records become `Absent` unless already `Present` or `Excused`. |
| **Inputs** | Session ID; open/close action |
| **Outputs** | Updated session state; attendance window timestamps; frozen roster after close |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §4.1; [BR-01](./04-business-rules.md) |

### FR-06 — Rotating dynamic QR display

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor` (display), `Student` (consumer via scan) |
| **Behavior** | While session is `Active`, server issues QR tokens with **30-second** validity. Instructor-facing display refreshes automatically each cycle and shows remaining seconds. Expired tokens transition to `Expired` and are rejected if scanned. Each token encodes a one-time-use identifier bound to the session. |
| **Inputs** | Active session ID |
| **Outputs** | QR image or deep link; token metadata (issue time, expiry); refresh every 30 s |
| **Traceability** | [BR-03](./04-business-rules.md), [BR-11](./04-business-rules.md); QR token states in [prompt.md](./prompt.md) §4.3 |

### FR-07 — Mobile web QR scan check-in

| Field | Specification |
| --- | --- |
| **Actor** | `Student` |
| **Behavior** | Student uses mobile browser camera to scan the displayed QR. No native app install required. **Default (simulation off):** client calls `navigator.mediaDevices.getUserMedia` for QR scan — no synthetic camera layer. After QR scan or deep-link token parse, client calls **`GET /api/v1/check-in/tokens/:tokenId/preflight`** (authenticated) **before** transitioning `scan` → `gps_capture`. Preflight checks (server-side, read-only): token exists; token status `Valid`; parent session `Active`; student has `Enrollment` for session's class-subject pair. **Pass:** advance to GPS step with session context (class code, subject, room) in GPS step header. **Fail:** remain on scan step or show outcome inline — do **not** start GPS capture ([BR-15](./04-business-rules.md)). Client extracts token from QR payload and submits check-in request with authenticated student identity. UI copy is Vietnamese (`vi-VN`). Successful check-in shows confirmation within 2 seconds under normal network conditions. |
| **Inputs** | QR token; authenticated student session |
| **Outputs** | Preflight pass → GPS step; attendance status update to `Present` on submit success; structured error code on failure |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §4.2; [08-validation-rules.md](../technical/08-validation-rules.md) preflight chain; platform: iOS 15+ Safari, Android 10+ Chrome; [NFR-24](./07-non-functional-risk.md) |

### FR-08 — GPS location verification

| Field | Specification |
| --- | --- |
| **Actor** | `Student` |
| **Behavior** | On check-in submit, client requests device geolocation permission and sends coordinates with the token. **Default (simulation off):** client calls `navigator.geolocation.getCurrentPosition` — no synthetic coordinates. **Simulation enabled:** when `VITE_ENABLE_DEVICE_SIMULATION=true`, URL query params (`gpsSim`, `cameraSim`, `gpsLat`/`gpsLng`) may override device APIs per [10-local-development-setup.md](../technical/10-local-development-setup.md). Server computes distance from device point to session room point using configured radius. Check-in succeeds only if distance ≤ radius. GPS disabled or permission denied rejects with `GpsDisabled`. **Ready-state UX:** when coordinates acquired (`ready`), hide spinner; show check icon + *Vị trí đã sẵn sàng* (static); `aria-busy="false"`; submit button enabled. Spinner only during `requesting` / `acquiring` / `submitting`. Session preflight (`sessionGate === "checking"`) may run in parallel but must not force GPS UI back to spinner once `ready`. Raw coordinates are used for validation only and are **not persisted** after successful check-in. |
| **Inputs** | Latitude, longitude, accuracy (if available); session room coordinates and radius |
| **Outputs** | `Present` or `OutOfRadius` / `GpsDisabled` outcome; distance logged for audit without long-term coordinate storage |
| **Traceability** | [BR-02](./04-business-rules.md), [BR-12](./04-business-rules.md); [12-ui-states.md](../ui-ux/12-ui-states.md) §4.2; privacy baseline [SM-04](./00-project-overview.md); [NFR-24](./07-non-functional-risk.md) |

### FR-09 — Anti-proxy and duplicate check-in prevention

| Field | Specification |
| --- | --- |
| **Actor** | `Student`, System |
| **Behavior** | System allows exactly one successful check-in per student account per session. A second attempt from the same account returns `DuplicateCheckIn` with HTTP 409 semantics. Each QR token may be consumed by at most one successful check-in; subsequent scan of a `Consumed` token is rejected and logged as potential code sharing. |
| **Inputs** | Student account ID, session ID, QR token |
| **Outputs** | Single `Present` record; conflict response on duplicate; security log entry on token reuse |
| **Traceability** | [BR-04](./04-business-rules.md), [BR-11](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §4.4 |

### FR-10 — Anti-GPS-spoofing baseline

| Field | Specification |
| --- | --- |
| **Actor** | System, `Instructor` |
| **Behavior** | System inspects platform signals where available (e.g., Android mock-location indicators, abnormally perfect accuracy) and flags `SpoofSuspected` on check-in attempt. Flagged attempts are rejected pending instructor review. Instructor may manually set student to `Present` after physical verification. All suspicious events are audit-logged. |
| **Inputs** | Device location metadata, platform hints |
| **Outputs** | `SpoofSuspected` rejection or pass-through to radius check; instructor alert in session monitor |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §4.4; capability: anti-GPS-spoofing baseline |

### FR-11 — Instructor manual attendance edit

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor`, `TrainingOfficeAdmin` (after 24 h) |
| **Behavior** | Instructor changes a student's attendance status among `Present`, `Absent`, `Excused`, and `Rejected` during an `Active` or `Closed` session, within **24 hours** of session close. Each edit writes an audit record: editor ID, timestamp, previous status, new status, optional note. After 24 hours, only `TrainingOfficeAdmin` may edit. |
| **Inputs** | Session ID, student ID, target status, optional note |
| **Outputs** | Updated attendance record; append-only audit log entry |
| **Traceability** | [BR-10](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §5.1 |

### FR-12 — Attendance reporting by class and subject

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor`, `TrainingOfficeAdmin` |
| **Behavior** | Instructor views attendance reports for assigned classes and subjects: per-session roster with status, session-level summary counts, and date-range aggregation. Training office admin views institution-wide reports with the same filters plus cross-cohort scope. Unauthorized access to another instructor's class is denied. Report tables support sort and pagination per [14-listing-pages-search-filter-sort.md](../ui-ux/14-listing-pages-search-filter-sort.md) §0. |
| **Inputs** | Class code, subject code, optional date range |
| **Outputs** | Paginated, sortable tabular report UI; summary metrics (present, absent, excused counts); inline **Xuất CSV** action on report pages ([AC-12d](../brds/08-acceptance-mvp-future.md)) |
| **Traceability** | [BR-08](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §6.1; [14-listing-pages-search-filter-sort.md](../ui-ux/14-listing-pages-search-filter-sort.md) §0; target: report within 10 minutes of close |

### FR-13 — CSV export from report pages

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor` (assigned class-subject scope), `TrainingOfficeAdmin` (institution-wide) |
| **Behavior** | Instructor and training office admin may export attendance data to CSV from any report page using active `ReportFilterBar` filters. Instructor export is limited to assigned class-subject pairs ([BR-08](./04-business-rules.md), [BR-09](./04-business-rules.md)). Admin export spans all cohorts within filters. CSV includes student ID, name, class, subject, session date, attendance status, and check-in timestamp when present. `Student` export attempts are rejected with localized permission error. All successful exports and denied attempts are audit-logged. |
| **Inputs** | Filter criteria matching on-screen report |
| **Outputs** | CSV file download; audit log of export action |
| **Traceability** | [BR-09](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §6.1–6.2; [14-listing-pages-search-filter-sort.md](../ui-ux/14-listing-pages-search-filter-sort.md) §10 |

### FR-14 — Student personal attendance history

| Field | Specification |
| --- | --- |
| **Actor** | `Student` |
| **Behavior** | Student views read-only list of own attendance records across enrolled subjects: session date, subject, status (`Present`, `Absent`, `Excused`), and check-in time when applicable. Student cannot view other students' records or institution-wide aggregates. |
| **Inputs** | Authenticated student session |
| **Outputs** | Paginated attendance history list |
| **Traceability** | [01-stakeholders-scope.md](./01-stakeholders-scope.md) §1.1; student stakeholder needs; list UX per [14-listing-pages-search-filter-sort.md](../ui-ux/14-listing-pages-search-filter-sort.md) §0 |

### FR-15 — Real-time attendance dashboard (Should)

| Field | Specification |
| --- | --- |
| **Actor** | `Instructor` |
| **Behavior** | During `Active` session, instructor sees live count of `Present` vs total enrolled and a sortable roster with per-student status. Dashboard refreshes within 5 seconds of each successful check-in without manual page reload. |
| **Inputs** | Active session ID |
| **Outputs** | Live metrics and roster grid |
| **Traceability** | [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.1.2 Should capability |

### FR-16 — Automatic absence threshold warning (Should)

| Field | Specification |
| --- | --- |
| **Actor** | System, `Student`, `Instructor` |
| **Behavior** | After each session close, system recalculates unexcused absence rate per student per subject. When rate exceeds **20%** of completed sessions, system sends in-app notification to the student and assigned instructor. `Excused` absences are excluded from the numerator. |
| **Inputs** | Updated attendance records; policy threshold from admin configuration |
| **Outputs** | Notification records; optional email if configured |
| **Traceability** | [BR-05](./04-business-rules.md); [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.1.2 |

### FR-17 — Initial admin bootstrap

| Field | Specification |
| --- | --- |
| **Actor** | Unauthenticated visitor (first deploy) |
| **Behavior** | `GET /api/v1/setup/status` returns `{ needsSetup: true }` when zero users exist. App redirects all routes (except `/setup`) to `/setup`. One-time form creates first `TrainingOfficeAdmin`. After success, `needsSetup: false`; endpoint returns 403 on repeat attempts. |
| **Inputs** | Institutional ID, display name, email, password (min strength per existing auth rules) |
| **Outputs** | First admin user + authenticated session; redirect to `/admin` hub |
| **Traceability** | [BR-13](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §3.0; [AC-17](./08-acceptance-mvp-future.md) |

### FR-18 — Permission-gated navigation and role home hubs

| Field | Specification |
| --- | --- |
| **Actor** | All authenticated roles; unauthenticated visitors on chrome-less routes |
| **Behavior** | **Nav visibility:** Each layout nav item (sidebar, bottom nav, quick-link card) maps to a required permission from [01-roles-permissions.md](../technical/01-roles-permissions.md) §2.1. Items the user lacks are **omitted** (not disabled, not shown). Cross-role routes never appear (e.g. instructor never sees admin sidebar items). **Active state:** At most one primary nav item per layout shows active styling; active link sets `aria-current="page"`. Route matching uses per-item `match` mode (`exact` or `prefix`) per [06-app-layout-components.md](../ui-ux/06-app-layout-components.md) §6.2a ([BR-14a](./04-business-rules.md)). **Role home:** After login (or visiting `/`), user lands on a role-specific hub page with navigation cards/buttons to permitted destinations and short workflow hints in Vietnamese. **Chrome-less navigation aids:** Routes without role layout chrome must expose at least one visible link or button to a sensible next destination — users must never need to memorize URLs. **`/` unauthenticated:** `ShellOverviewPage` renders a **Route discovery** section below the component showcase: grouped quick links with Vietnamese labels to `/login`, `/check-in`, `/sessions`, `/admin`. Protected targets still auth-redirect per [BR-06](./04-business-rules.md). Section hidden when authenticated ([AC-18g](./08-acceptance-mvp-future.md); [AC-18e](./08-acceptance-mvp-future.md) redirect applies). **Auth routes:** `/login` footer includes optional *Quay về trang chủ* → `/`. `/setup` when `needsSetup: false` shows link to `/login` ([AC-17c](./08-acceptance-mvp-future.md)). **Error routes:** `/forbidden` and `*` 404 recovery CTA targets role home when authenticated or `/login` when unauthenticated (extends existing *Về trang chủ* semantics). |
| **Inputs** | Current `AuthSession` role + permission set; auth state for chrome-less routes |
| **Outputs** | Filtered nav chrome with singleton active indicator; hub page with deep links to feature routes; route discovery panel on unauthenticated `/` |
| **Traceability** | [BR-14](./04-business-rules.md), [BR-14a](./04-business-rules.md); [06-app-layout-components.md](../ui-ux/06-app-layout-components.md); [AC-18](./08-acceptance-mvp-future.md); [NFR-11](./07-non-functional-risk.md); [NFR-17](./07-non-functional-risk.md) |

---

## 3. Requirement Traceability Matrix

| FR ID | Workflow section | Business rules | MVP priority |
| --- | --- | --- | --- |
| FR-01 | §3.1 | — | Must |
| FR-02 | §4.2 | BR-06 | Must |
| FR-03 | §3.1 | — | Must |
| FR-04 | §3.2 | BR-07 | Must |
| FR-05 | §4.1 | BR-01 | Must |
| FR-06 | §4.1, §4.2 | BR-03, BR-11 | Must |
| FR-07 | §4.2 | BR-03, BR-15 | Must |
| FR-08 | §4.2 | BR-02, BR-12 | Must |
| FR-17 | §3.0 | BR-13 | Must |
| FR-18 | §3.0 | BR-14, BR-14a | Must |
| FR-09 | §4.4 | BR-04, BR-11 | Must |
| FR-10 | §4.4 | — | Must |
| FR-11 | §5.1 | BR-10 | Must |
| FR-12 | §6.1 | BR-08 | Must |
| FR-13 | §6.2 | BR-09 | Must |
| FR-14 | §4.2 | — | Must |
| FR-15 | §4.1 | — | Should |
| FR-16 | §6.1 | BR-05 | Should |

---

## 4. Out of Scope (Functional)

The following are explicitly **not** functional requirements in MVP:

| Excluded capability | Rationale |
| --- | --- |
| Facial recognition | Out of MVP per [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.2 |
| Tuition payment | Unrelated domain |
| Exam schedule management | Separate academic module |
| Native mobile apps | Mobile web only |
| Offline check-in queue | Network retry only |
| SSO / campus IdP | Future consideration — email/password auth in MVP |

---

## 5. Future Consideration

| Enhancement | Affected FR area |
| --- | --- |
| SSO integration | FR-02 authentication flow |
| WiFi BSSID verification | FR-08 location verification |
| PIN-based fallback check-in | New FR for alternate channel |
| Academic API roster sync | FR-03 replaces CSV-only path |
| Two-factor authentication | FR-02 hardening |
| Permission onboarding copy (first check-in) | FR-07 UX extension — Vietnamese guided consent |

Detailed acceptance tests for Must requirements: [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) (`AC-xx`).
