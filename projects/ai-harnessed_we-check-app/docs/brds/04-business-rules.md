# We Check — Business Rules

Enforceable business rules (`BR-xx`) for **We Check** MVP. Each rule defines condition, trigger, outcome, scope, and exceptions. Rules refine functional requirements in [03-functional-requirements.md](./03-functional-requirements.md) and align with canonical states in [prompt.md](./prompt.md) §4.

**Related documents:** [Business workflow](./02-business-workflow.md) · [Functional requirements](./03-functional-requirements.md) · [State machine](./05-state-machine.md) · [Domain model](./06-domain-model.md) · [Acceptance criteria](./08-acceptance-mvp-future.md)

---

## 1. Business Rules Overview

| Category | Rule IDs | Primary enforcement point |
| --- | --- | --- |
| Session lifecycle and attendance window | BR-01 | Session close and late check-in rejection |
| Location verification | BR-02, BR-12 | Check-in submission |
| QR token integrity | BR-03, BR-11 | Token issuance and consumption |
| Anti-proxy / duplicate prevention | BR-04 | Check-in submission |
| Absence policy | BR-05 | Post-session batch job |
| Authentication | BR-06 | All protected actions |
| Session activation prerequisites | BR-07 | Session `Draft` → `Active` |
| Authorization (reports and export) | BR-08, BR-09 | Report and export endpoints |
| Manual corrections | BR-10 | Instructor and admin attendance edits |
| Bootstrap and navigation | BR-13, BR-14, BR-14a | First deploy setup; nav chrome; singleton active indicator |
| Check-in preflight gate | BR-15 | Before GPS capture step |

Rules marked **Must** block the operation when violated. **Should** rules (BR-05) run asynchronously after session close.

---

## 2. Session Lifecycle Rules

### BR-01 — Attendance window and auto-close

| Field | Specification |
| --- | --- |
| **Condition** | Current time is after the attendance window end, where window end = `scheduledStartTime` + **10 minutes**, unless instructor manually closed earlier |
| **Trigger** | Student submits check-in; system scheduler runs auto-close; instructor closes session |
| **Outcome** | While session is `Active` and current time ≤ window end: check-in allowed per other rules. After window end or on manual close: session transitions to `Closed`; all `Pending` attendance records become `Absent`; late check-in attempts return `SessionNotActive` with localized message |
| **Scope** | All enrolled students in the session |
| **Exceptions** | Instructor may manually mark a student `Present` or `Excused` after close within edit policy ([BR-10](./04-business-rules.md#br-10--manual-attendance-edit-window)) |
| **Traceability** | [FR-05](./03-functional-requirements.md); [05-state-machine.md](./05-state-machine.md) §2.1 |

### BR-07 — Session activation requires room GPS

| Field | Specification |
| --- | --- |
| **Condition** | Session record lacks valid room latitude and longitude (finite values within Earth bounds: latitude −90..90, longitude −180..180) |
| **Trigger** | Instructor requests `Draft` → `Active` transition |
| **Outcome** | Transition blocked; UI displays message requiring room GPS configuration before opening check-in |
| **Scope** | Instructor-owned sessions |
| **Exceptions** | None — GPS coordinates are mandatory for location verification ([BR-02](./04-business-rules.md#br-02--gps-radius-verification)) |
| **Traceability** | [FR-04](./03-functional-requirements.md); [06-domain-model.md](./06-domain-model.md) §3.4 `Session` |

---

## 3. Check-In and Token Rules

### BR-03 — QR token 30-second validity

| Field | Specification |
| --- | --- |
| **Condition** | `currentTime` > `tokenIssuedAt` + **30 seconds** |
| **Trigger** | Student scans QR and submits token for check-in |
| **Outcome** | Check-in rejected with outcome `ExpiredQr`; token state `Expired`; UI message (Vietnamese): *Mã QR đã hết hạn, vui lòng quét mã mới* |
| **Scope** | All check-in attempts |
| **Exceptions** | None — 30-second window is absolute to prevent screenshot sharing |
| **Traceability** | [FR-06](./03-functional-requirements.md), [FR-07](./03-functional-requirements.md); [05-state-machine.md](./05-state-machine.md) §2.3 |

### BR-11 — One-time-use QR token consumption

| Field | Specification |
| --- | --- |
| **Condition** | Token state is `Consumed` (already used for one successful check-in) |
| **Trigger** | Any student submits a previously consumed token while still within the 30-second validity window |
| **Outcome** | Check-in rejected; security log entry with session ID, token ID, and submitting student ID; instructor monitor may show code-sharing alert |
| **Scope** | All students |
| **Exceptions** | None — each token supports at most one successful consumption |
| **Traceability** | [FR-06](./03-functional-requirements.md), [FR-09](./03-functional-requirements.md); [06-domain-model.md](./06-domain-model.md) §3.6 `QrToken` |

### BR-04 — One successful check-in per student per session

| Field | Specification |
| --- | --- |
| **Condition** | Student account already has attendance status `Present` (or `Excused` set after a successful check-in) for the session |
| **Trigger** | Same student submits a second check-in request in the same session |
| **Outcome** | HTTP 409 semantics with outcome `DuplicateCheckIn`; UI message (Vietnamese): *Bạn đã điểm danh buổi học này rồi*; no duplicate `Present` record |
| **Scope** | All enrolled students |
| **Exceptions** | None — prevents proxy check-in via shared accounts |
| **Traceability** | [FR-09](./03-functional-requirements.md); [02-business-workflow.md](./02-business-workflow.md) §4.4 |

---

## 4. Location and Identity Rules

### BR-02 — GPS radius verification

| Field | Specification |
| --- | --- |
| **Condition** | Haversine distance from device coordinates to session room coordinates > session `gpsRadiusMeters` (default **100 m**, instructor-adjustable at session creation) |
| **Trigger** | Student submits check-in with latitude and longitude |
| **Outcome** | Check-in rejected with outcome `OutOfRadius`; attendance record remains `Pending` or moves to `Rejected` depending on attempt logging policy; distance value logged for audit without persisting raw coordinates long-term |
| **Scope** | All check-in attempts while session is `Active` |
| **Exceptions** | Instructor manual override to `Present` after physical verification ([BR-10](./04-business-rules.md#br-10--manual-attendance-edit-window)); [FR-10](./03-functional-requirements.md) spoof handling runs before radius check |
| **Traceability** | [FR-08](./03-functional-requirements.md); [06-domain-model.md](./06-domain-model.md) §3.4 `Session.roomLocation` |

### BR-12 — GPS permission required

| Field | Specification |
| --- | --- |
| **Condition** | Client cannot obtain device geolocation (permission denied, GPS disabled, or timeout after configured client wait of 15 seconds) |
| **Trigger** | Student initiates check-in flow |
| **Outcome** | Check-in rejected with outcome `GpsDisabled`; UI message (Vietnamese): *Vui lòng bật GPS và cấp quyền định vị để điểm danh* with link to permission help |
| **Scope** | All mobile web check-in attempts |
| **Exceptions** | None for automated check-in — instructor manual attendance is the fallback ([BR-10](./04-business-rules.md#br-10--manual-attendance-edit-window)) |
| **Traceability** | [FR-08](./03-functional-requirements.md); privacy baseline in [00-project-overview.md](./00-project-overview.md) |

### BR-06 — Authentication required before check-in

| Field | Specification |
| --- | --- |
| **Condition** | Request lacks valid authenticated session (expired, missing, or deactivated user) |
| **Trigger** | Student accesses check-in URL or submits check-in payload |
| **Outcome** | Redirect to login; check-in not recorded; outcome `Unauthenticated` if API called directly |
| **Scope** | All students and protected instructor/admin actions |
| **Exceptions** | None — identity binding is mandatory for anti-proxy controls ([BR-04](./04-business-rules.md#br-04--one-successful-check-in-per-student-per-session)) |
| **Traceability** | [FR-02](./03-functional-requirements.md); [02-business-workflow.md](./02-business-workflow.md) §4.2 |

---

## 5. Authorization and Data Access Rules

### BR-08 — Report access by assignment

| Field | Specification |
| --- | --- |
| **Condition** | User is not `TrainingOfficeAdmin` and is not the instructor assigned to the requested class/subject |
| **Trigger** | User opens attendance report filtered by class or subject |
| **Outcome** | Access denied with localized permission error; no data returned |
| **Scope** | Class- and subject-scoped reports |
| **Exceptions** | `TrainingOfficeAdmin` has institution-wide read access |
| **Traceability** | [FR-12](./03-functional-requirements.md); [06-domain-model.md](./06-domain-model.md) §3.2 `ClassAssignment` |

### BR-09 — CSV export scoped by role

| Field | Specification |
| --- | --- |
| **Condition** | User requests CSV export outside permitted scope |
| **Trigger** | `POST /reports/export` or inline **Xuất CSV** on a report page |
| **Outcome** | **Instructor:** export allowed only for assigned class-subject pairs ([BR-08](./04-business-rules.md)); out-of-scope request denied with localized permission error; audit log records denied attempt. **TrainingOfficeAdmin:** export allowed for any class/subject within active filters. **Student:** export always denied; UI hides export control; API message (Vietnamese): *Chỉ phòng đào tạo mới có quyền xuất dữ liệu*; denied attempt logged |
| **Scope** | All export endpoints and report-page export actions |
| **Exceptions** | Instructor scoped export per assignment; admin institution-wide export |
| **Traceability** | [FR-13](./03-functional-requirements.md); [02-business-workflow.md](./02-business-workflow.md) §6.1–6.2; [14-listing-pages-search-filter-sort.md](../ui-ux/14-listing-pages-search-filter-sort.md) §10 |

---

## 6. Attendance Correction and Policy Rules

### BR-10 — Manual attendance edit window

| Field | Specification |
| --- | --- |
| **Condition** | Elapsed time since session `closedAt` ≤ **24 hours** for `Instructor`; any time for `TrainingOfficeAdmin` after 24 hours |
| **Trigger** | Instructor or admin changes student attendance status among `Present`, `Absent`, `Excused`, `Rejected` |
| **Outcome** | Status updated; append-only audit record created with editor ID, timestamp, previous status, new status, optional note |
| **Scope** | Sessions owned by the instructor; institution-wide for admin |
| **Exceptions** | After 24 hours, instructor edits blocked; only `TrainingOfficeAdmin` may edit. `Rejected` → `Present` allowed as spoof override per [FR-10](./03-functional-requirements.md) |
| **Traceability** | [FR-11](./03-functional-requirements.md); [06-domain-model.md](./06-domain-model.md) §3.8 `AttendanceAuditLog` |

### BR-05 — Automatic absence threshold warning (Should)

| Field | Specification |
| --- | --- |
| **Condition** | Unexcused absence rate for a student in a subject exceeds **20%** of completed sessions: `(count of Absent) / (count of completed sessions) > 0.20`, excluding `Excused` from numerator |
| **Trigger** | System recalculates rates after each session transitions to `Closed` |
| **Outcome** | In-app notification to affected student and assigned instructor; optional email if admin enables outbound mail |
| **Scope** | All enrolled students per subject |
| **Exceptions** | `Excused` absences excluded; sessions still `Active` or `Draft` excluded from denominator |
| **Traceability** | [FR-16](./03-functional-requirements.md); [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.1.2 |

---

## 7. Bootstrap and Navigation Rules

### BR-13 — One-time admin bootstrap

| Field | Specification |
| --- | --- |
| **Condition** | `User.count = 0` in the deployment database |
| **Trigger** | Visitor loads any route; `GET /api/v1/setup/status` polled on app boot |
| **Outcome** | While count is zero: `needsSetup: true`; all routes except `/setup` redirect to `/setup`; `POST /api/v1/setup/first-admin` creates exactly one `TrainingOfficeAdmin` and establishes session. After first admin exists: `needsSetup: false`; `/setup` returns 403 or redirects to login; repeat `POST` rejected with `SetupAlreadyComplete` |
| **Scope** | Entire deployment — exactly one bootstrap transaction permitted |
| **Exceptions** | None — bootstrap is not available when any user record exists |
| **Traceability** | [FR-17](./03-functional-requirements.md); [AC-17](./08-acceptance-mvp-future.md) |

### BR-14 — Permission-gated navigation chrome

| Field | Specification |
| --- | --- |
| **Condition** | Authenticated user lacks permission required for a nav item's destination route |
| **Trigger** | Layout renders sidebar, bottom nav, or hub quick-link cards |
| **Outcome** | Nav item is **omitted** from DOM (not disabled, not shown). Cross-role route prefixes never appear (e.g. instructor chrome contains zero `href` values under `/admin/*`). Direct URL access to forbidden routes still returns `ForbiddenPage` |
| **Scope** | All authenticated roles; all layout chrome |
| **Exceptions** | None — showing a nav item the user cannot access is a spec violation |
| **Traceability** | [FR-18](./03-functional-requirements.md); [NFR-11](./07-non-functional-risk.md); [AC-18](./08-acceptance-mvp-future.md) |

### BR-14a — Singleton active nav indicator

| Field | Specification |
| --- | --- |
| **Condition** | Layout chrome renders sidebar or bottom nav with multiple items whose routes share a URL prefix (e.g. `/admin/rosters` and `/admin/rosters/import`) |
| **Trigger** | User navigates to any protected route within a role shell |
| **Outcome** | Exactly **zero or one** nav link displays active styling (`--color-primary-50` background, `--color-primary-700` text) and `aria-current="page"`. When a more specific nav item matches the current path, its parent prefix item must **not** also appear active. Route-to-item matching rules are defined in [06-app-layout-components.md](../ui-ux/06-app-layout-components.md) §6.2a |
| **Scope** | All authenticated role shells — `StudentLayout`, `InstructorLayout`, `AdminLayout` |
| **Exceptions** | Hub quick-link cards on role home pages are not primary nav items and do not participate in singleton active state |
| **Traceability** | [FR-18](./03-functional-requirements.md); [AC-18h](./08-acceptance-mvp-future.md) |

### BR-15 — QR preflight gate before GPS capture

| Field | Specification |
| --- | --- |
| **Condition** | Student has scanned QR or parsed deep-link token but preflight has not returned success |
| **Trigger** | Client attempts transition from `scan` → `gps_capture` |
| **Outcome** | Client calls `GET /api/v1/check-in/tokens/:tokenId/preflight` first. Check-in flow must **not** enter `gps_capture` until preflight succeeds for the authenticated student's enrollment scope. Failures keep user on scan step or show outcome inline per preflight outcome table in [FR-07](./03-functional-requirements.md) |
| **Scope** | All student check-in flows including deep links |
| **Exceptions** | None — GPS capture and submit never start on failed preflight |
| **Traceability** | [FR-07](./03-functional-requirements.md); [AC-07c](./08-acceptance-mvp-future.md)–[AC-07f](./08-acceptance-mvp-future.md) |

---

## 8. Rule Interaction Matrix

Check-in evaluation order when session is `Active` and within attendance window ([BR-01](./04-business-rules.md#br-01--attendance-window-and-auto-close)):

**Client-side preflight (before GPS step):** [BR-15](./04-business-rules.md#br-15--qr-preflight-gate-before-gps-capture) — token exists, `Valid`, session `Active`, student enrolled. Failures do not mount `GpsCaptureStep`.

**Server-side submit evaluation:**

| Order | Rule | Failure outcome |
| --- | --- | --- |
| 1 | BR-06 | `Unauthenticated` |
| 2 | Session state `Active` | `SessionNotActive` |
| 3 | BR-03 | `ExpiredQr` |
| 4 | BR-11 (token already consumed) | Reject + security log |
| 5 | BR-04 | `DuplicateCheckIn` |
| 6 | BR-12 | `GpsDisabled` |
| 7 | FR-10 spoof signals | `SpoofSuspected` |
| 8 | BR-02 | `OutOfRadius` |
| 9 | — | `Success` → `Present`, token `Consumed` |

---

## 9. Rule Traceability to Functional Requirements

| BR ID | FR IDs | Workflow section |
| --- | --- | --- |
| BR-13 | FR-17 | [02-business-workflow.md](./02-business-workflow.md) §3.0 |
| BR-14 | FR-18 | §3.0 |
| BR-14a | FR-18 | §3.0 |
| BR-15 | FR-07 | §4.2 |
| BR-01 | FR-05 | [02-business-workflow.md](./02-business-workflow.md) §4.1 |
| BR-02 | FR-08 | §4.2 |
| BR-03 | FR-06, FR-07 | §4.1, §4.2 |
| BR-04 | FR-09 | §4.4 |
| BR-05 | FR-16 | §6.1 |
| BR-06 | FR-02 | §4.2 |
| BR-07 | FR-04 | §3.2 |
| BR-08 | FR-12 | §6.1 |
| BR-09 | FR-13 | §6.2 |
| BR-10 | FR-11 | §5.1 |
| BR-11 | FR-06, FR-09 | §4.1, §4.4 |
| BR-12 | FR-08 | §4.2 |

---

## 10. Future Consideration

| Enhancement | Affected rules |
| --- | --- |
| WiFi BSSID indoor verification | Extends BR-02 with secondary proximity signal |
| Instructor manual attendance window extension | BR-01 exception path beyond 24-hour edit |
| Configurable QR validity (not recommended) | Would weaken BR-03 — defer unless policy changes |
| PIN-based fallback when device unavailable | New rule parallel to BR-12 exceptions |
| Device fingerprint on token reuse | Strengthens BR-11 logging and alerts |
