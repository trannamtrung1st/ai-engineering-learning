# Attendly — Functional Requirements

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [01-stakeholders-scope.md](./01-stakeholders-scope.md) · [02-business-workflow.md](./02-business-workflow.md) · [04-business-rules.md](./04-business-rules.md) · [05-state-machine.md](./05-state-machine.md) · [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md)

**Convention:** Each `FR-xx` entry lists **Actor**, **Behavior**, **Priority** (`Must` / `Should`), and **Trace** to capability IDs (`CAP-xx`) from [01-stakeholders-scope.md](./01-stakeholders-scope.md). Business rule enforcement is specified in [04-business-rules.md](./04-business-rules.md).

---

## 1. Functional Requirements

### 1.1 Summary matrix

| ID range | Domain | MVP priority |
| --- | --- | --- |
| FR-01 – FR-05 | Academic structure and enrollment | Must |
| FR-06 – FR-10 | Class sessions and attendance window | Must |
| FR-11 – FR-18 | QR tokens and student check-in | Must |
| FR-19 – FR-23 | Lecturer dashboard and manual fallback | Must |
| FR-24 – FR-26 | Attendance policy | Should |
| FR-27 – FR-28 | Reporting and export | Must / Should |
| FR-29 – FR-30 | Audit logging | Must |
| FR-31 – FR-33 | Department admin and system auditor | Should |
| FR-34 – FR-35 | GPS validation | Should |
| FR-36 – FR-37 | Authentication and student self-service | Must |

---

## 2. Academic structure and enrollment

### FR-01 — Manage academic terms

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Create, view, update, and deactivate academic terms (semesters). Each term has name, start date, end date, and active flag. Class sections are created within exactly one term. |
| **Priority** | Must |
| **Trace** | CAP-01 |

### FR-02 — Manage courses

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Create and maintain course records (subject code, name, credit units optional, faculty assignment). Courses may be reused across terms; class sections link a course to a specific term offering. |
| **Priority** | Must |
| **Trace** | CAP-01 |

### FR-03 — Manage class sections

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Create class sections binding a course, term, assigned lecturer, default room, and schedule template. Support list, search, filter, and detail views. Section is the enrollment and attendance scope for students and lecturers. |
| **Priority** | Must |
| **Trace** | CAP-01 |

### FR-04 — Import student enrollments

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Import enrolled students per class section via CSV upload (MVP). Validate required fields (student identifier, section reference). Report row-level errors without silently skipping invalid rows. Support add and remove enrollment with effective check-in eligibility on next attempt. |
| **Priority** | Must |
| **Trace** | CAP-02 |

### FR-05 — Manage rooms and locations

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Define rooms with name, building, and optional latitude/longitude for GPS validation. Assign default room to class section and override per session when class meets elsewhere. |
| **Priority** | Should (required when GPS policy enabled) |
| **Trace** | CAP-10 |

---

## 3. Class sessions and attendance window

### FR-06 — Generate and manage class sessions

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin, Lecturer (view) |
| **Behavior** | Create class sessions for a section from timetable template or manually when schedule changes. Each session stores scheduled start time, duration, room, and initial state `Scheduled`. Support cancel session → `Cancelled`. |
| **Priority** | Must |
| **Trace** | CAP-03 |

### FR-07 — Open attendance window

| Field | Value |
| --- | --- |
| **Actor** | Lecturer |
| **Behavior** | Transition assigned session from `Scheduled` to `Open`. Only the lecturer assigned to the section (or delegate per policy) may open. Reject open request if session is `Cancelled` or already `Closed`. Record open timestamp and actor. |
| **Priority** | Must |
| **Trace** | CAP-04 |

### FR-08 — Close attendance window

| Field | Value |
| --- | --- |
| **Actor** | Lecturer, System (auto-close) |
| **Behavior** | Transition session from `Open` to `Closed`. Lecturer may close manually. System may auto-close when policy late window elapses. After close, reject new student check-in attempts. |
| **Priority** | Must |
| **Trace** | CAP-04 |

### FR-09 — Auto-absent on session close

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | When session becomes `Closed`, mark each enrolled student without a successful attendance record as `Absent` unless already `Excused` or `Manual Present`. Apply per effective attendance policy. |
| **Priority** | Must |
| **Trace** | CAP-13, BR-13 |

### FR-10 — Session list for lecturer

| Field | Value |
| --- | --- |
| **Actor** | Lecturer |
| **Behavior** | Display upcoming and today's sessions across assigned sections with status badge (`Scheduled`, `Open`, `Closed`, `Cancelled`), enrolled count, and quick actions (open, view roster). |
| **Priority** | Must |
| **Trace** | CAP-03, CAP-04 |

---

## 4. QR session tokens

### FR-11 — Issue rotating session QR tokens

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | While session is `Open`, issue QR session tokens bound to exactly one class session. Token TTL is **30 seconds**. Display QR refreshes automatically before expiry. Token encodes check-in URL or opaque token resolvable server-side. |
| **Priority** | Must |
| **Trace** | CAP-05 |

### FR-12 — Multi-use token within TTL

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Allow multiple enrolled students to submit check-in using the same valid token within its TTL. Token is **not** globally one-time-use. Invalidate token after TTL → state `Expired`. |
| **Priority** | Must |
| **Trace** | CAP-05, BR-03 |

### FR-13 — Reject expired or invalid tokens

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Reject check-in when token is `Expired`, `Invalid`, malformed, or belongs to a different session. Return user-facing message instructing student to scan the current QR. Log failed attempt with reason code `ExpiredQr` or equivalent. |
| **Priority** | Must |
| **Trace** | CAP-05, BR-03, BR-04 |

### FR-14 — Projection-friendly QR display

| Field | Value |
| --- | --- |
| **Actor** | Lecturer |
| **Behavior** | Render large, high-contrast QR on lecturer view suitable for projector or classroom display. Show session name, section code, countdown or refresh indicator, and open/closed status. |
| **Priority** | Must |
| **Trace** | CAP-05, CAP-12 |

---

## 5. Student authentication and check-in

### FR-15 — Student authentication gate

| Field | Value |
| --- | --- |
| **Actor** | Student, System |
| **Behavior** | Require authenticated student session before check-in submission. Unauthenticated users opening check-in URL are redirected to login and returned to check-in after success. MVP supports local credentials or imported accounts; SSO is future. |
| **Priority** | Must |
| **Trace** | CAP-07, BR-05 |

### FR-16 — Mobile web QR scan entry

| Field | Value |
| --- | --- |
| **Actor** | Student |
| **Behavior** | Support check-in flow in mobile browser (iOS Safari, Android Chrome). Student scans QR via camera; no native app install. Deep link or URL carries session token for server validation. |
| **Priority** | Must |
| **Trace** | CAP-06 |

### FR-17 — Enrollment validation at check-in

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Verify submitting student has active enrollment in the session's class section. Reject with reason `NotEnrolled` and log attempt if not enrolled. |
| **Priority** | Must |
| **Trace** | CAP-08, BR-06 |

### FR-18 — One successful check-in per student per session

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Permit at most one successful attendance record per student per class session. Subsequent attempts rejected with `DuplicateCheckIn` and message that student already checked in. |
| **Priority** | Must |
| **Trace** | CAP-09, BR-07 |

### FR-36 — Student login and account access

| Field | Value |
| --- | --- |
| **Actor** | Student |
| **Behavior** | Sign in with institution-issued credentials. Lock or throttle repeated failed logins per security policy. Password reset or account recovery follows IT admin configuration (MVP: admin-assisted reset acceptable). |
| **Priority** | Must |
| **Trace** | CAP-07 |

### FR-37 — Personal attendance history

| Field | Value |
| --- | --- |
| **Actor** | Student |
| **Behavior** | View own attendance records per enrolled section and session: status, check-in timestamp, method (`QR`, `Manual`, `Admin Correction`). Deny access to other students' records and institution-wide export. |
| **Priority** | Must |
| **Trace** | CAP-14 |

---

## 6. GPS location verification

### FR-34 — Request GPS at check-in when required

| Field | Value |
| --- | --- |
| **Actor** | Student, System |
| **Behavior** | When effective policy requires GPS, prompt student for browser location permission at check-in only—not continuous tracking. Collect latitude, longitude, and accuracy once per attempt. Explain purpose in Vietnamese UI copy. |
| **Priority** | Should |
| **Trace** | CAP-10, BR-08 |

### FR-35 — Validate GPS against room radius

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Compare device coordinates to session room location within configurable radius (default **100 m**). Reject or flag `Suspicious` when outside radius, permission denied, or accuracy worse than configured threshold. GPS reduces remote check-in risk; system does **not** claim absolute anti-spoofing. |
| **Priority** | Should |
| **Trace** | CAP-10, BR-08, BR-09, BR-10 |

---

## 7. Check-in processing and attendance records

### FR-19 — Realtime lecturer attendance dashboard

| Field | Value |
| --- | --- |
| **Actor** | Lecturer |
| **Behavior** | During `Open` session, show live roster: students checked in (`Present`/`Late`), pending (no successful check-in), and rejected attempts with reason. Update without full page reload where technically feasible. |
| **Priority** | Must |
| **Trace** | CAP-12 |

### FR-20 — Lecturer manual attendance correction

| Field | Value |
| --- | --- |
| **Actor** | Lecturer |
| **Behavior** | Set or change attendance status for students in assigned sections (`Manual Present`, `Excused`, `Late`, etc.) with required reason field when policy mandates. Enforce section scope and manual-edit time window. Reject edits outside window unless escalated to admin. |
| **Priority** | Must |
| **Trace** | CAP-11, BR-14, BR-15 |

### FR-21 — Academic admin attendance correction

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Override attendance records within authorized scope when lecturer window expired or dispute requires admin action. Require reason; write full audit entry with old and new values. |
| **Priority** | Must |
| **Trace** | CAP-11, BR-16 |

### FR-22 — Record check-in attempts

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Persist every check-in attempt with student, session, token reference, timestamp, outcome (`Success`, rejection reason code), optional GPS validation result, and minimal device metadata. **100%** of failed attempts include structured reason code. |
| **Priority** | Must |
| **Trace** | CAP-16 |

### FR-23 — Assign Present or Late on success

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | On successful check-in, set `Present` if within present window or `Late` if after present window but before session close, per effective policy. Store check-in timestamp and method `QR`. |
| **Priority** | Must |
| **Trace** | BR-11, BR-12 |

---

## 8. Attendance policy

### FR-24 — Configure attendance policies

| Field | Value |
| --- | --- |
| **Actor** | Academic Admin |
| **Behavior** | Define policies at institution, faculty, course, or class-section level: check-in opening offset, present window, late window, auto-close rule, absence threshold, excused-absence handling, manual-edit window, admin-approval rule, GPS required flag, GPS radius. |
| **Priority** | Should |
| **Trace** | CAP-13 |

### FR-25 — Resolve effective policy per session

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | At check-in and session close, resolve single effective policy for the class section using precedence (section overrides course overrides faculty overrides institution defaults). |
| **Priority** | Should |
| **Trace** | CAP-13 |

### FR-26 — Absence threshold alerts

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | When student's unexcused absence rate for a section exceeds configured threshold (e.g., 20%), notify student, lecturer, and/or academic admin per policy. Excused absences may be excluded from calculation. |
| **Priority** | Should |
| **Trace** | BR-17 |

---

## 9. Reporting and export

### FR-27 — Basic attendance CSV export

| Field | Value |
| --- | --- |
| **Actor** | Lecturer, Academic Admin |
| **Behavior** | Export attendance data to CSV scoped by role: lecturer exports own sections only; academic admin exports authorized institution scope. Include student identifier, session, status, timestamps, method. Deny export to students and unauthorized roles. |
| **Priority** | Must |
| **Trace** | CAP-15, BR-18, BR-19 |

### FR-28 — Attendance reports and filters

| Field | Value |
| --- | --- |
| **Actor** | Lecturer, Academic Admin, Department Admin |
| **Behavior** | Generate in-app attendance reports filtered by student, class section, course, lecturer, and term. Support search, filter, sort, and pagination on listing views. Extended Excel format is future; MVP CSV satisfies core compliance need. |
| **Priority** | Should |
| **Trace** | CAP-14 |

---

## 10. Audit logging

### FR-29 — Audit log for attendance mutations

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Log every manual attendance create/update/delete with actor, timestamp, target student and session, previous value, new value, and reason. **100%** coverage required. |
| **Priority** | Must |
| **Trace** | CAP-16 |

### FR-30 — Audit log for exports and sensitive reads

| Field | Value |
| --- | --- |
| **Actor** | System |
| **Behavior** | Log every export action with actor, timestamp, scope, and format. Log privileged access to bulk attendance or audit views when institution policy requires. Retain logs per retention policy. |
| **Priority** | Must |
| **Trace** | CAP-16, BR-18 |

---

## 11. Extended roles

### FR-31 — Department admin faculty scope

| Field | Value |
| --- | --- |
| **Actor** | Department Admin |
| **Behavior** | Grant read and limited write within assigned faculty: view department reports, handle exceptions for department sections, correct attendance per department policy. Deny access to other faculties' data. |
| **Priority** | Should |
| **Trace** | — |

### FR-32 — System auditor read-only access

| Field | Value |
| --- | --- |
| **Actor** | System Auditor |
| **Behavior** | Provide read-only search across audit logs and attendance records within granted scope. No create, update, or delete of academic records. Support dispute investigation workflows in [02-business-workflow.md](./02-business-workflow.md) §8. |
| **Priority** | Should |
| **Trace** | CAP-16 |

### FR-33 — IT admin platform operations

| Field | Value |
| --- | --- |
| **Actor** | IT Admin |
| **Behavior** | Manage technical configuration, user account provisioning integration, operational logs, and system health views. IT Admin does not edit attendance records unless explicitly granted academic role. |
| **Priority** | Must (operational); academic edits out of scope |
| **Trace** | — |

---

## 12. Check-in rejection reason codes

The system must support the following canonical attempt outcomes (align with [prompt.md](./prompt.md) §4.4):

| Code | Meaning | Related FR |
| --- | --- | --- |
| `Success` | Check-in accepted | FR-23 |
| `ExpiredQr` | Token past 30 s TTL | FR-13 |
| `SessionNotOpen` | Session not yet `Open` | FR-07, BR-01 |
| `SessionClosed` | Session already `Closed` | FR-08, BR-02 |
| `NotEnrolled` | Student not in section roster | FR-17 |
| `DuplicateCheckIn` | Student already checked in | FR-18 |
| `GpsRequired` | Policy requires GPS not yet provided | FR-34 |
| `GpsDisabled` | Permission denied | FR-35, BR-08 |
| `OutOfRadius` | Coordinates outside allowed radius | FR-35, BR-09 |
| `LowAccuracy` | Accuracy below threshold | FR-35, BR-10 |
| `Unauthenticated` | No valid login | FR-15 |
| `Suspicious` | Anomaly flagged for review | FR-35, BR-10 |

---

## 13. Requirement traceability

| Capability | Functional requirements |
| --- | --- |
| CAP-01 Class section management | FR-01, FR-02, FR-03 |
| CAP-02 Enrollment | FR-04 |
| CAP-03 Timetable / sessions | FR-06, FR-10 |
| CAP-04 Open/close attendance | FR-07, FR-08 |
| CAP-05 Dynamic QR | FR-11, FR-12, FR-13, FR-14 |
| CAP-06 Mobile web check-in | FR-16 |
| CAP-07 Student auth | FR-15, FR-36 |
| CAP-08 Enrollment validation | FR-17 |
| CAP-09 Duplicate prevention | FR-18 |
| CAP-10 GPS validation | FR-05, FR-34, FR-35 |
| CAP-11 Manual fallback | FR-20, FR-21 |
| CAP-12 Realtime dashboard | FR-19, FR-14 |
| CAP-13 Attendance policy | FR-09, FR-24, FR-25, FR-26 |
| CAP-14 Reports | FR-28, FR-37 |
| CAP-15 Export | FR-27 |
| CAP-16 Audit log | FR-22, FR-29, FR-30, FR-32 |

Business rules (`BR-xx`), non-functional requirements (`NFR-xx`), and acceptance criteria (`AC-xx`) are defined in sibling documents and must remain consistent with this set.

---

## 14. Future consideration

Functional enhancements deferred beyond MVP:

- **FR-F01** — Campus SSO and MFA integration
- **FR-F02** — REST API for enrollment sync and attendance webhooks
- **FR-F03** — Per-student one-time challenge token after QR scan
- **FR-F04** — Offline check-in queue with idempotent sync
- **FR-F05** — Device binding and login anomaly detection
- **FR-F06** — Random mid-session verification prompts
- **FR-F07** — Excel export and scheduled report jobs
- **FR-F08** — WiFi or indoor positioning aids for GPS-challenged buildings
- **FR-F09** — Facial verification check-in (policy and legal review required)

Phasing detail: [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).
