# Attendly — Stakeholders and Scope

**Product:** Attendly (*Smart Campus Attendance*)  
**Related docs:** [00-project-overview.md](./00-project-overview.md) · [02-business-workflow.md](./02-business-workflow.md) · [03-functional-requirements.md](./03-functional-requirements.md) · [04-business-rules.md](./04-business-rules.md)

---

## 1. Stakeholders

### 1.1 Stakeholder map

| Stakeholder group | Primary role in Attendly | Pain point | Expected benefit |
| --- | --- | --- | --- |
| **Student** | Check in via mobile web; view personal attendance history | Waits for manual roll call; risk of wrongful absence | Fast phone check-in; transparent personal record |
| **Lecturer** | Open/close sessions, display QR, monitor roster, manual corrections | 5–15 minutes lost per session to manual attendance | Minutes to start session; realtime visibility; exception handling |
| **Department Admin** | Faculty-scoped oversight, exceptions, aggregated reports | Limited visibility into department attendance trends | Department-level reports and policy exception handling |
| **Academic Admin** | Terms, courses, sections, enrollment, policies, institution reports | Unreliable cross-campus attendance data | Authoritative structure, policy control, compliance export |
| **IT Admin** | Platform operations, technical configuration, operational logs | Needs centralized, secure, auditable system | RBAC, audit trails, operational monitoring |
| **System Auditor** | Read-only audit and attendance views for disputes | Complaints lack traceable evidence | Full audit trail access without academic write risk |
| **Institution leadership** | Consumes aggregated attendance insights | Quality-of-education decisions lack timely data | Trustworthy reports by class, subject, and term |

### 1.2 System roles and actors

Attendly defines six application roles. Actor labels match [product-meta.json](../product-meta.json).

| Role | Actor label | Primary responsibilities | MVP access |
| --- | --- | --- | --- |
| Student | `Student` | Scan session QR, grant camera/GPS when required, view personal attendance history | Own attendance and enrolled sessions only |
| Lecturer | `Lecturer` | Open/close session attendance, display QR, monitor live roster, manual corrections, section-level reports and export | Class sections they teach |
| Department Admin | `DepartmentAdmin` | Faculty-scoped oversight, exception handling, aggregated reports within department | Department-scoped read/write per policy |
| Academic Admin | `AcademicAdmin` | Terms, courses, sections, enrollment, attendance policies, institution-wide reports and export | Authorized academic scope (typically institution-wide) |
| IT Admin | `ITAdmin` | System operations, technical configuration, operational logs | Technical admin; no academic data edits unless explicitly granted |
| System Auditor | `SystemAuditor` | Review audit trails for disputes and compliance checks | Read-only audit and attendance views per grant |

**Decision authority:**

| Domain | Authority |
| --- | --- |
| Attendance policies and academic structure | Academic Admin |
| Per-session attendance operations | Lecturer |
| Student check-in consumption | Student (self-service only) |
| Platform reliability and technical config | IT Admin |
| Dispute review without record mutation | System Auditor |
| Department-level exceptions and reports | Department Admin (within assigned faculty) |

Technical permission matrices are detailed in [docs/technical/01-roles-permissions.md](../technical/01-roles-permissions.md) when available.

### 1.3 Stakeholder engagement by phase

| Phase | Primary stakeholders | Engagement focus |
| --- | --- | --- |
| MVP (Phase 1) | Lecturer, Student, Academic Admin | Core check-in, manual fallback, basic export |
| Phase 2 | Academic Admin, Department Admin | Policy configuration, extended reporting, absence alerts |
| Phase 3 | IT Admin, Academic Admin | SSO, academic system integration, load hardening |
| Phase 4 | Institution leadership, IT Admin | Advanced anti-fraud (optional, policy-driven) |

---

## 2. Scope

MVP aligns with **Phase 1 — Core Attendance**. Items marked **Must** are non-negotiable for launch; **Should** items ship if schedule allows. Full acceptance criteria: [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).

### 2.1 In scope — Must (MVP)

| Capability | MVP behavior | Trace |
| --- | --- | --- |
| Academic structure (minimal) | Manage terms, courses, and class sections with assigned lecturer; sufficient to schedule sessions and enroll students | CAP-01 |
| Student enrollment | Import or sync enrolled students per class section (CSV acceptable for MVP) | CAP-02 |
| Timetable and class sessions | Define scheduled sessions per class section; support manual session creation when timetable changes | CAP-03 |
| Open/close attendance window | Lecturer opens and closes check-in for a specific class session; reject check-in when session not open | CAP-04 |
| Rotating dynamic QR (30 s) | Server issues **short-lived multi-use** session tokens bound to one class session; QR display refreshes every **30 seconds**; expired tokens rejected with clear message | CAP-05 |
| Mobile web QR scan | Student uses phone browser camera; no native app | CAP-06 |
| Student authentication | Valid login required before check-in; unauthenticated users redirected to login | CAP-07 |
| Enrollment validation | Only students enrolled in the class section may check in; failures logged as rejected attempts | CAP-08 |
| One check-in per student per session | Each student may have at most one **successful** attendance record per class session; duplicate attempts rejected with explicit message | CAP-09 |
| Attendance statuses (core) | Record `Present`, `Late`, `Absent`, and `Manual Present` where policy applies; store rejected attempts separately | — |
| Lecturer manual fallback | Lecturer may mark or correct attendance for students in their class sections when device/network/GPS issues occur; changes audit-logged | CAP-11 |
| Realtime lecturer dashboard (basic) | During an open session, lecturer sees checked-in, not checked-in, and rejected students for that session | CAP-12 |
| Basic attendance CSV export | Role-scoped export for lecturer (own sections) and academic admin (authorized scope) | CAP-15 |
| Audit logging (core) | Log successful check-ins, failed attempts with reason, manual edits, and export actions | CAP-16 |

### 2.2 In scope — Should (include if schedule allows)

| Capability | MVP behavior | Trace |
| --- | --- | --- |
| GPS location verification | When class/section policy requires GPS, compare device coordinates to room location within configurable radius (default **100 m**); reject or flag when outside radius, permission denied, or accuracy too low | CAP-10 |
| Attendance policy configuration | Academic admin configures present/late windows, auto-absent rules, absence thresholds, and manual-edit windows at school/faculty/course/section levels where feasible | CAP-13 |
| Extended statuses | `Excused`, `Suspicious`, and structured rejection reason codes on attempts | — |
| Absence threshold alerts | Notify student/lecturer/admin when unexcused absence rate exceeds policy threshold (e.g., 20%) | — |
| Department admin scope | Faculty-level read and exception handling within assigned department | — |
| System auditor read-only | View audit logs for dispute resolution without academic write access | — |
| Attendance reports (extended) | Reports by student, class, subject, lecturer, and term beyond basic CSV | CAP-14 |

### 2.3 Out of scope (MVP)

The following are explicitly **out of scope** for MVP launch:

| Item | Rationale |
| --- | --- |
| Facial recognition | Privacy, legal, and implementation complexity; deferred to future phase if institution requires |
| Native iOS/Android apps | MVP is mobile-web only; native app enables richer device signals in future |
| Tuition payment | Unrelated to attendance domain |
| Exam schedule management | Out of attendance product boundary |
| Full learning management system (LMS) | Attendly integrates with academic data; it does not replace LMS |
| Absolute GPS spoofing detection | Mobile web cannot reliably detect all mock-location tools |
| Guaranteed mock-location detection on all devices | Platform limitation; GPS reduces risk but does not eliminate it |
| Continuous student location tracking outside check-in | Privacy minimization; GPS collected only at check-in moment when required |
| Deep two-way integration with legacy student information systems | MVP uses import/CSV; API integration is future |
| Offline check-in queue with deferred sync | MVP supports retry on poor network only |
| Per-student one-time QR challenge tokens | Future hardening option after core flow is stable |
| Grading and academic assessment | Separate academic domain |

### 2.4 Scope boundaries and dependencies

**Data inputs (MVP):**

- Class section, course, and term definitions from academic admin
- Student enrollment lists via CSV import (API sync is future)
- Room/location coordinates when GPS policy is enabled
- Attendance policy defaults with optional per-section overrides (Should)

**Data outputs (MVP):**

- Per-session attendance records with status and timestamps
- Check-in attempt log with rejection reason codes
- Audit log for manual edits and exports
- CSV export scoped by role

**External dependencies:**

- Institution provides enrollment and roster data
- Students have smartphones with camera and mobile browser
- Campus HTTPS connectivity during class sessions
- Lecturer display device (projector, large monitor, or laptop) for QR

**QR token model (critical):** The session QR is a **short-lived multi-use** token—not one-time-use globally. One-time rule applies to each student's **successful** check-in per session, not to the shared QR code. See [04-business-rules.md](./04-business-rules.md) (`BR-03`, `BR-07`) and [05-state-machine.md](./05-state-machine.md).

### 2.5 Future consideration

Enhancements deferred beyond MVP:

- SSO / campus identity provider and MFA
- Device binding and random in-class verification prompts
- WiFi BSSID or indoor positioning aids
- Timetable sync automation from campus systems
- Native app for richer device signals
- Face verification where legally permitted
- Advanced cross-signal fraud analytics
- API-first export and webhook integrations for academic systems
- Long-term GPS retention policies beyond dispute-review windows
- Per-student one-time check-in challenge tokens
- Offline queue with deferred sync for poor-network environments

Delivery phasing detail: [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).
