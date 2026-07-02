# Attendly — Project Overview

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Locale:** Vietnamese (`vi-VN`) UI copy; technical identifiers in English  
**Related docs:** [01-stakeholders-scope.md](./01-stakeholders-scope.md) · [02-business-workflow.md](./02-business-workflow.md) · [03-functional-requirements.md](./03-functional-requirements.md) · [product-meta.json](../product-meta.json)

---

## 1. Project Overview

Attendly is a responsive web and mobile-web attendance system for universities and campus training offices. It replaces manual roll call—calling names, paper sign-in sheets, and hand-typed lists—with a digital check-in flow built around short-lived rotating QR codes, student login, enrollment validation, optional GPS verification, realtime lecturer dashboards, manual fallback for legitimate device failures, and attendance reporting across terms and semesters.

**Primary value proposition:**

- **Lecturers** open a class session and display a rotating QR in minutes instead of spending 5–15 minutes on manual roll call.
- **Students** check in from a phone browser without installing a native app.
- **Academic administrators** gain trustworthy attendance data, configurable policies, and export for academic compliance and dispute resolution.

**Anti-fraud posture:** Attendly **reduces** proxy and remote check-in risk through login, short-lived session QR, enrollment checks, one-successful-check-in-per-student, optional GPS, suspicious-attempt logging, and manual review. It does **not** guarantee absolute GPS spoofing detection or elimination of all fraud on mobile web. See [07-non-functional-risk.md](./07-non-functional-risk.md) for privacy and risk detail.

**Platform:** Responsive web; mobile-first student check-in; projection-friendly lecturer QR display. Target browsers: iOS Safari and Android Chrome versions common on student devices.

---

## 2. Business Context

### 2.1 Problem statement

Campus classes still rely heavily on manual or semi-manual attendance processes. This creates systemic problems:

| Pain area | Impact |
| --- | --- |
| Lecturer time | 5–15 minutes per session lost to calling names, paper sign-in, or manual list entry |
| Data quality | Hand-entered attendance is error-prone—missing students, duplicates, late updates |
| Proxy check-in | Without strong identity controls, students can check in on behalf of others |
| Academic oversight | Training offices struggle to track absence and lateness rates by class, subject, and term |
| Dispute resolution | Post-session complaints lack clear audit trails and reconcilable evidence |

### 2.2 Organization context

Attendly serves **university and campus training offices** that manage class sections, timetables, attendance policies, and academic compliance reporting. Typical deployment context:

- Multiple faculties or departments under one institution
- Class sections tied to courses and terms/semesters
- Lecturers assigned per section; students enrolled per section
- Academic admins configure structure and policies; IT admins operate the platform

### 2.3 Solution summary

Attendly digitizes the attendance moment for each **class session**:

1. Lecturer opens the attendance window for a scheduled session.
2. System issues a **short-lived multi-use** QR token (30-second TTL) bound to that session.
3. Students scan the QR with a mobile browser, authenticate, pass enrollment and duplicate checks, and optionally pass GPS validation when policy requires it.
4. System records `Present`, `Late`, `Absent`, or `Manual Present` per student; logs all failed attempts with reason codes.
5. Lecturers monitor a realtime roster; academic staff export role-scoped reports.

Canonical state names and transitions are defined in [05-state-machine.md](./05-state-machine.md). Domain entities are in [06-domain-model.md](./06-domain-model.md).

---

## 3. Objectives

### 3.1 Strategic goals

| ID | Goal | User / business value | Metric | Target | Timeframe |
| --- | --- | --- | --- | --- | --- |
| OBJ-01 | Automate class attendance | Reduce manual roll-call burden on lecturers | Majority of enrolled students checked in | **< 5 minutes** per session | Each class session |
| OBJ-02 | Improve attendance data accuracy | Training offices get reliable class/subject data | Valid attendance record rate | **≥ 98%** | Per term |
| OBJ-03 | Reduce proxy check-in risk | Limit QR sharing, remote check-in, and duplicate attempts | Failed/suspicious attempts logged with reason | **100%** | Each session |
| OBJ-04 | Support academic administration | Track absence, lateness, and excused absence | Attendance report generation time | **< 10 minutes** | Per class/subject/term scope |
| OBJ-05 | Handle legitimate exceptions | Avoid wrongful absence when device, network, or GPS fails | Exception cases resolvable via manual fallback | **≥ 95%** | Each session |

### 3.2 Operational success metrics

| Metric | Target | Notes |
| --- | --- | --- |
| Median check-in time per student | **< 30 seconds** | From QR scan to success confirmation |
| 95th percentile check-in time | **< 90 seconds** | Includes login and optional GPS grant |
| Valid check-in processing success rate | **≥ 99%** | Server-side processing of eligible attempts |
| Manual fallback rate | **< 5%** of students per session | Legitimate device/network/GPS failures |
| Failed attempt reason code coverage | **100%** | Every rejected attempt has a structured reason |
| Attendance edit audit coverage | **100%** | Every manual correction logged |
| Export action audit coverage | **100%** | Every export logged with actor and scope |
| System availability during school hours | Per institution SLA | Defined with IT admin and academic leadership |

### 3.3 MVP delivery focus

MVP aligns with **Phase 1 — Core Attendance** (see [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md)). Non-negotiable launch capabilities:

- Academic structure (terms, courses, class sections with assigned lecturer)
- Student enrollment import (CSV acceptable)
- Class session scheduling and open/close attendance window
- Rotating dynamic QR (30-second TTL, multi-use per session)
- Mobile web QR scan with student login
- Enrollment validation and one successful check-in per student per session
- Core attendance statuses: `Present`, `Late`, `Absent`, `Manual Present`
- Lecturer manual fallback with audit logging
- Basic realtime lecturer dashboard
- Role-scoped CSV export
- Core audit logging for check-ins, failures, edits, and exports

Capabilities marked **Should** in [01-stakeholders-scope.md](./01-stakeholders-scope.md) may ship in MVP if schedule allows (GPS verification, extended policy configuration, department admin scope, system auditor role).

### 3.4 Key constraints and assumptions

| ID | Type | Statement |
| --- | --- | --- |
| C-01 | Constraint | Web/mobile-web only—no native app APIs for mock-GPS detection |
| C-02 | Constraint | Students need smartphone with camera; manual fallback required for exceptions |
| C-03 | Constraint | Campus network may be unstable—retry UX and manual fallback essential |
| C-04 | Constraint | Institution may lack stable SSO at launch—local login or account import acceptable for MVP |
| C-05 | Constraint | Attendance and location data are sensitive—RBAC, audit, and retention policies required |
| A-01 | Assumption | Majority of students have suitable smartphones |
| A-02 | Assumption | Institution provides enrollment data via CSV or API |
| A-03 | Assumption | Lecturers accept opening QR at session start after brief training |
| A-04 | Assumption | GPS radius is configurable per room/location with field testing |
| A-05 | Assumption | Manual fallback is required policy to prevent wrongful absence |

Full constraint and risk detail: [07-non-functional-risk.md](./07-non-functional-risk.md).

---

## 4. Document map

| Document | Purpose |
| --- | --- |
| [00-project-overview.md](./00-project-overview.md) | Vision, objectives, metrics (this document) |
| [01-stakeholders-scope.md](./01-stakeholders-scope.md) | Stakeholders, roles, in/out scope |
| [02-business-workflow.md](./02-business-workflow.md) | End-to-end flows |
| [03-functional-requirements.md](./03-functional-requirements.md) | `FR-xx` functional requirements |
| [04-business-rules.md](./04-business-rules.md) | `BR-xx` business rules |
| [05-state-machine.md](./05-state-machine.md) | Session, attendance, and QR token states |
| [06-domain-model.md](./06-domain-model.md) | Entities and relationships |
| [07-non-functional-risk.md](./07-non-functional-risk.md) | `NFR-xx`, risks, privacy |
| [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) | `AC-xx`, MVP vs future phases |
