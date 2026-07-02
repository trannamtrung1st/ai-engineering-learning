# Attendly — MVP BRD and UI Design Prompt

Condensed product brief for generating Business Requirements Documents and UI/UX specifications. Source: [initial idea](../initial-idea.md), [product metadata](../product-meta.json).

---

## 1. Product Goal

**Attendly** (*Smart Campus Attendance*) is a web and mobile-web digital attendance system for universities and campus training offices. It replaces manual roll call (calling names, paper sign-in, hand-typed lists) for class sections with rotating QR check-in, student login, enrollment validation, optional GPS verification, realtime lecturer dashboards, manual fallback, and attendance reporting across terms and semesters.

| Dimension | Target |
| --- | --- |
| Domain | Digital campus attendance and class-session check-in for universities and schools |
| Locale | Vietnamese (`vi-VN`) UI copy; technical docs may use English identifiers |
| Check-in completion | Majority of enrolled students checked in within **5 minutes** per class session |
| Median check-in time | **< 30 seconds** per student |
| Valid attendance record rate | ≥ **98%** per term |
| Report generation | Attendance report exportable within **10 minutes** for class/subject/term scope |
| Manual fallback rate | < **5%** of students per session |
| Failed/suspicious attempts logged | **100%** with reason code |

**Problem to solve:** Manual attendance wastes 5–15 minutes per session for lecturers, produces unreliable attendance data for academic offices, enables proxy check-in without strong identity controls, and leaves disputes without audit trails.

**Primary value:** Lecturers open a session and display a rotating QR in minutes; students check in from a phone browser without installing an app; academic administrators gain trustworthy attendance data, policy configuration, and export for academic compliance.

**Anti-fraud posture:** Attendly **reduces** proxy and remote check-in risk through login, short-lived session QR, enrollment checks, one-successful-check-in-per-student, optional GPS, suspicious-attempt logging, and manual review. It does **not** guarantee absolute GPS spoofing detection or elimination of all fraud on mobile web.

---

## 2. MVP Scope

MVP aligns with **Phase 1 — Core Attendance** from the source BRD. Capabilities marked **Should** in the source may ship in MVP if schedule allows; **Must** items are non-negotiable for launch.

### 2.1 In scope (Must)

| Capability | MVP behavior |
| --- | --- |
| Academic structure (minimal) | Manage terms, courses, and class sections with assigned lecturer; sufficient to schedule sessions and enroll students |
| Student enrollment | Import or sync enrolled students per class section (CSV acceptable for MVP) |
| Timetable and class sessions | Define scheduled sessions per class section; support manual session creation when timetable changes |
| Open/close attendance window | Lecturer opens and closes check-in for a specific class session; reject check-in when session not open |
| Rotating dynamic QR (30 s) | Server issues **short-lived multi-use** session tokens bound to one class session; QR display refreshes every **30 seconds**; expired tokens rejected with clear message |
| Mobile web QR scan | Student uses phone browser camera; no native app |
| Student authentication | Valid login required before check-in; unauthenticated users redirected to login |
| Enrollment validation | Only students enrolled in the class section may check in; failures logged as rejected attempts |
| One check-in per student per session | Each student may have at most one **successful** attendance record per class session; duplicate attempts rejected with explicit message |
| Attendance statuses (core) | Record `Present`, `Late`, `Absent`, and `Manual Present` where policy applies; store rejected attempts separately |
| Lecturer manual fallback | Lecturer may mark or correct attendance for students in their class sections when device/network/GPS issues occur; changes audit-logged |
| Realtime lecturer dashboard (basic) | During an open session, lecturer sees checked-in, not checked-in, and rejected students for that session |
| Basic attendance CSV export | Role-scoped export for lecturer (own sections) and academic admin (authorized scope) |
| Audit logging (core) | Log successful check-ins, failed attempts with reason, manual edits, and export actions |

### 2.2 In scope (Should — include if schedule allows)

| Capability | MVP behavior |
| --- | --- |
| GPS location verification | When class/section policy requires GPS, compare device coordinates to room location within configurable radius (default **100 m**); reject or flag when outside radius, permission denied, or accuracy too low |
| Attendance policy configuration | Academic admin configures present/late windows, auto-absent rules, absence thresholds, and manual-edit windows at school/faculty/course/section levels where feasible |
| Extended statuses | `Excused`, `Suspicious`, and structured rejection reason codes on attempts |
| Absence threshold alerts | Notify student/lecturer/admin when unexcused absence rate exceeds policy threshold (e.g., 20%) |
| Department admin scope | Faculty-level read and exception handling within assigned department |
| System auditor read-only | View audit logs for dispute resolution without academic write access |

### 2.3 Out of scope (MVP)

- Facial recognition
- Native iOS/Android apps
- Tuition payment
- Exam schedule management
- Full learning management system (LMS)
- Absolute GPS spoofing detection or guaranteed mock-location detection on all devices
- Continuous student location tracking outside check-in moment
- Deep two-way integration with legacy student information systems (MVP uses import/CSV; API integration is future)
- Offline check-in queue with deferred sync (retry on poor network only)
- Per-student one-time QR challenge tokens (future hardening option)

### 2.4 Future consideration

- SSO / campus identity provider and MFA
- Device binding and random in-class verification prompts
- WiFi BSSID or indoor positioning aids
- Timetable sync automation from campus systems
- Native app for richer device signals
- Face verification where legally permitted
- Advanced cross-signal fraud analytics
- API-first export and webhook integrations for academic systems
- Long-term GPS retention policies beyond dispute-review windows

---

## 3. Roles

| Role | Actor label | Primary responsibilities | MVP access |
| --- | --- | --- | --- |
| Student | `Student` | Scan session QR, grant camera/GPS when required, view personal attendance history | Own attendance and enrolled sessions only |
| Lecturer | `Lecturer` | Open/close session attendance, display QR, monitor live roster, manual corrections, section-level reports and export | Class sections they teach |
| Department Admin | `DepartmentAdmin` | Faculty-scoped oversight, exception handling, aggregated reports within department | Department-scoped read/write per policy |
| Academic Admin | `AcademicAdmin` | Terms, courses, sections, enrollment, attendance policies, institution-wide reports and export | Authorized academic scope (typically institution-wide) |
| IT Admin | `ITAdmin` | System operations, technical configuration, operational logs | Technical admin; no academic data edits unless explicitly granted |
| System Auditor | `SystemAuditor` | Review audit trails for disputes and compliance checks | Read-only audit and attendance views per grant |

**Decision authority:** Academic admin defines attendance policies and academic structure; lecturers operationalize per session; students consume check-in flows only; IT admin owns platform reliability; auditors review without mutating academic records.

Cross-reference: full stakeholder detail belongs in [01-stakeholders-scope.md](./01-stakeholders-scope.md).

---

## 4. Canonical States

Downstream BRD and UI docs must use these state names consistently.

### 4.1 Class session attendance window

| State | Meaning | Allowed transitions |
| --- | --- | --- |
| `Scheduled` | Session exists on timetable; attendance not yet open | → `Open`, → `Cancelled` |
| `Open` | Lecturer opened check-in; QR active; students may attempt check-in | → `Closed` |
| `Closed` | Check-in window ended; roster frozen except manual edits within policy | (terminal for MVP check-in) |
| `Cancelled` | Session will not run or attendance abandoned | (terminal) |

**Attendance window:** From session open until lecturer close or policy auto-close. Present vs Late determined by configured present and late windows relative to session start.

### 4.2 Attendance record (per student per class session)

| State | Meaning |
| --- | --- |
| `Pending` | Enrolled; no successful check-in yet while session is `Open` |
| `Present` | Successful check-in within present window |
| `Late` | Successful check-in after present window but before close, per policy |
| `Absent` | Session closed without successful check-in and no excused/manual override |
| `Excused` | Documented excused absence per policy |
| `Manual Present` | Lecturer or admin recorded attendance manually after verification |
| `Rejected` | Check-in attempt failed — may transition to `Present`, `Late`, or `Manual Present` via manual override |

Attempt-level labels (not final roster state): `Rejected Attempt`, `Suspicious` — used for logging and review before a final record is set.

### 4.3 QR session token

| State | Meaning |
| --- | --- |
| `Valid` | Issued for a class session, within **30 s** TTL, may be used by **multiple enrolled students** until expiry |
| `Expired` | Past TTL; students must scan the refreshed QR |
| `Invalid` | Wrong session, revoked, or malformed — all check-ins rejected |

**Critical model:** QR token is **not** one-time-use globally. One-time rule applies to **each student’s successful check-in per session**, not to the shared QR code.

### 4.4 Check-in attempt outcome (API/UI)

`Success` | `ExpiredQr` | `SessionNotOpen` | `SessionClosed` | `NotEnrolled` | `DuplicateCheckIn` | `GpsRequired` | `GpsDisabled` | `OutOfRadius` | `LowAccuracy` | `Unauthenticated` | `Suspicious`

State diagrams: [05-state-machine.md](./05-state-machine.md).

---

## 5. Output Rules

Documents produced from this prompt must follow these conventions.

### 5.1 Document set and numbering

| File | Purpose |
| --- | --- |
| [00-project-overview.md](./00-project-overview.md) | Vision, objectives, metrics |
| [01-stakeholders-scope.md](./01-stakeholders-scope.md) | Stakeholders, in/out scope |
| [02-business-workflow.md](./02-business-workflow.md) | End-to-end flows (student, lecturer, academic admin) |
| [03-functional-requirements.md](./03-functional-requirements.md) | `FR-xx` requirements |
| [04-business-rules.md](./04-business-rules.md) | `BR-xx` rules |
| [05-state-machine.md](./05-state-machine.md) | State transitions |
| [06-domain-model.md](./06-domain-model.md) | Entities and relationships |
| [07-non-functional-risk.md](./07-non-functional-risk.md) | `NFR-xx`, risks, privacy |
| [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) | `AC-xx`, MVP vs future |

### 5.2 Requirement ID formats

- **Functional:** `FR-01`, `FR-02`, … — each with Actor, Behavior, and trace to capabilities in §2
- **Business rules:** `BR-01`, … — condition, trigger, outcome, exceptions (preserve rules from source BRD such as session-not-open, expired QR, duplicate check-in, GPS policy)
- **Non-functional:** `NFR-01`, … — measurable quality attributes (availability during school hours, audit completeness, data minimization)
- **Acceptance:** `AC-01`, … — testable Given/When/Then criteria tied to `FR-xx`

IDs must be unique across the BRD set.

### 5.3 Writing standards

- Use numbered markdown sections (`## 1.`, `### 1.1`)
- Product name **Attendly** in user-facing references
- MVP-only in main body; defer enhancements to **Future consideration**
- No ambiguous placeholders; resolve open questions with explicit MVP defaults (e.g., QR TTL **30 s**, default GPS radius **100 m** when GPS is enabled, manual fallback always available for legitimate device failures)
- Cross-link related sections by filename and requirement ID
- Privacy: collect GPS only at check-in when policy requires; minimize retention of raw coordinates; document retention and dispute handling aligned with campus data-protection expectations
- Platform: responsive web; prioritize mobile-first student check-in and projection-friendly lecturer QR display; test targets iOS Safari and Android Chrome versions common on student devices
- Wording: say GPS validation **reduces remote check-in risk**; never claim **absolute anti-spoofing**

### 5.4 UI/UX derivation

UI specs under `docs/ui-ux/` must map pages and flows to `FR-xx` and `AC-xx`. Authoritative visual spec: [DESIGN.md](../ui-ux/DESIGN.md) and [design-system modules](../ui-ux/design-system/). Design tokens map through [04-design-tokens.md](../ui-ux/04-design-tokens.md). Style: **Neobrutalism** — primary `#FFDB33`, `2px solid #000000` borders, `0px` default radius, hard offset shadows, **Archivo Black** headings, **Space Grotesk** body.

Prioritize:

- Mobile-first student QR scan → login gate → optional GPS → result screen with clear success/failure copy in Vietnamese
- Lecturer session control: open/close, large rotating QR, realtime roster with Present/Late/Absent/Pending and rejected attempts
- Academic admin listing pages with search, filter, sort, and pagination per route matrix
- `TableToolbar` on privileged and listing routes
- Permission-denied and recovery paths (expired QR, GPS denied, duplicate check-in, not enrolled)
- Manual attendance edit with reason capture and confirmation

Reference this prompt for scope boundaries before adding screens.

### 5.5 Key business rules to preserve in BR-xx

- QR token TTL: **30 seconds**; token is **multi-use** within TTL for the same class session
- One **successful** check-in per student per class session
- Check-in rejected when session not `Open`, token expired, student not enrolled, or student already checked in
- Login required before check-in submission
- GPS checks apply only when policy for that class section requires GPS; manual fallback when self check-in cannot complete
- Lecturer manual edits limited to their sections and within configured edit window; academic admin may override per policy
- Every failed attempt, manual edit, and export action produces an audit log entry with actor, timestamp, and reason where applicable
- Export scoped by role: lecturer within assigned sections; academic admin within authorized scope; student denied institution-wide export

---

*This prompt is the single source of truth for MVP scope when BRD and UI documents conflict with the initial idea draft.*
