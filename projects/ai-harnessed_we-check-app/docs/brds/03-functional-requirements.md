# We Check — Functional Requirements

Implementable functional requirements (`FR-xx`) for **We Check** MVP. Each requirement specifies actor, behavior, inputs, outputs, and traceability to business workflows and capabilities defined in [prompt.md](./prompt.md) and [01-stakeholders-scope.md](./01-stakeholders-scope.md).

**Related documents:** [Business workflow](./02-business-workflow.md) · [Business rules](./04-business-rules.md) · [State machine](./05-state-machine.md) · [Domain model](./06-domain-model.md) · [Acceptance criteria](./08-acceptance-mvp-future.md)

---

## 1. Functional Requirements Overview

| ID range | Capability area | MVP priority |
| --- | --- | --- |
| FR-01 – FR-03 | Identity, authentication, roster | Must |
| FR-04 – FR-05 | Session creation and lifecycle | Must |
| FR-06 – FR-09 | QR check-in, GPS, anti-fraud | Must |
| FR-10 – FR-11 | Student history and manual corrections | Must |
| FR-12 – FR-13 | Reporting and CSV export | Must |
| FR-14 – FR-16 | Should-capability enhancements | Should |

Business rules (`BR-xx`) refine enforcement; acceptance tests (`AC-xx`) are defined in [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).

---

## 2. Functional Requirements

### FR-01 — User account provisioning

| Field | Specification |
| --- | --- |
| **Actor** | `TrainingOfficeAdmin` |
| **Behavior** | Admin creates, updates, and deactivates user accounts for students and instructors. Each account has a unique institutional identifier (student ID or staff ID), display name, email, role assignment, and active flag. Deactivated users cannot log in or check in. |
| **Inputs** | User profile fields; role (`Student`, `Instructor`, `TrainingOfficeAdmin`); optional bulk CSV upload |
| **Outputs** | Persisted user record; validation errors for duplicate IDs or invalid email |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §3.1; capability: roster management baseline |

### FR-02 — Authentication before check-in

| Field | Specification |
| --- | --- |
| **Actor** | `Student`, `Instructor`, `TrainingOfficeAdmin` |
| **Behavior** | System requires a valid authenticated session before any check-in submission or protected report action. Unauthenticated users attempting check-in are redirected to the login page. After successful login, the user returns to the intended check-in flow. Session expires after configurable inactivity (default 8 hours). |
| **Inputs** | Email (or institutional username) and password |
| **Outputs** | Auth session token; redirect to original URL on success; localized error on failure |
| **Traceability** | [BR-06](./04-business-rules.md); workflow: [02-business-workflow.md](./02-business-workflow.md) §4.2 step 2 |

### FR-03 — Roster import and maintenance

| Field | Specification |
| --- | --- |
| **Actor** | `TrainingOfficeAdmin`, `Instructor` (read-only roster view) |
| **Behavior** | Admin imports class rosters via CSV when academic API is unavailable. Required columns: student ID, full name, class code, subject code. System validates format, rejects duplicate student IDs within a class, and surfaces row-level errors without partial silent failure. Instructor views enrolled students for assigned classes only. |
| **Inputs** | CSV file; class and subject identifiers |
| **Outputs** | Enrollment records linked to students; import summary (accepted, rejected rows) |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §3.1; [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.1.1 |

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
| **Behavior** | Student uses mobile browser camera to scan the displayed QR. No native app install required. Client extracts token from QR payload and submits check-in request with authenticated student identity. UI copy is Vietnamese (`vi-VN`). Successful check-in shows confirmation within 2 seconds under normal network conditions. |
| **Inputs** | QR token; authenticated student session |
| **Outputs** | Attendance status update to `Present` on success; structured error code on failure |
| **Traceability** | [02-business-workflow.md](./02-business-workflow.md) §4.2; platform: iOS 15+ Safari, Android 10+ Chrome |

### FR-08 — GPS location verification

| Field | Specification |
| --- | --- |
| **Actor** | `Student` |
| **Behavior** | On check-in submit, client requests device geolocation permission and sends coordinates with the token. Server computes distance from device point to session room point using configured radius. Check-in succeeds only if distance ≤ radius. GPS disabled or permission denied rejects with `GpsDisabled`. Raw coordinates are used for validation only and are **not persisted** after successful check-in. |
| **Inputs** | Latitude, longitude, accuracy (if available); session room coordinates and radius |
| **Outputs** | `Present` or `OutOfRadius` / `GpsDisabled` outcome; distance logged for audit without long-term coordinate storage |
| **Traceability** | [BR-02](./04-business-rules.md), [BR-12](./04-business-rules.md); privacy baseline [SM-04](./00-project-overview.md) |

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
| **Behavior** | Instructor views attendance reports for assigned classes and subjects: per-session roster with status, session-level summary counts, and date-range aggregation. Training office admin views institution-wide reports with the same filters plus cross-cohort scope. Unauthorized access to another instructor's class is denied. |
| **Inputs** | Class code, subject code, optional date range |
| **Outputs** | Tabular report UI; summary metrics (present, absent, excused counts) |
| **Traceability** | [BR-08](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §6.1; target: report within 10 minutes of close |

### FR-13 — CSV export for training office

| Field | Specification |
| --- | --- |
| **Actor** | `TrainingOfficeAdmin` |
| **Behavior** | Only users with `TrainingOfficeAdmin` role may export attendance data to CSV. Export respects current report filters (class, subject, date range). CSV includes student ID, name, class, subject, session date, attendance status, and check-in timestamp when present. Non-admin export attempts are rejected with localized permission error. |
| **Inputs** | Filter criteria matching on-screen report |
| **Outputs** | CSV file download; audit log of export action |
| **Traceability** | [BR-09](./04-business-rules.md); [02-business-workflow.md](./02-business-workflow.md) §6.2 |

### FR-14 — Student personal attendance history

| Field | Specification |
| --- | --- |
| **Actor** | `Student` |
| **Behavior** | Student views read-only list of own attendance records across enrolled subjects: session date, subject, status (`Present`, `Absent`, `Excused`), and check-in time when applicable. Student cannot view other students' records or institution-wide aggregates. |
| **Inputs** | Authenticated student session |
| **Outputs** | Paginated attendance history list |
| **Traceability** | [01-stakeholders-scope.md](./01-stakeholders-scope.md) §1.1; student stakeholder needs |

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
| FR-07 | §4.2 | BR-03 | Must |
| FR-08 | §4.2 | BR-02, BR-12 | Must |
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
