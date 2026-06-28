# We Check — Project Overview

Business Requirements Document foundation for **We Check**, a digital attendance and session check-in system for the Harness Engineering for Software Development (HESD) workshop program and institutional training office operations.

**Related documents:** [MVP BRD prompt](./prompt.md) · [Initial idea](../initial-idea.md) · [Stakeholders and scope](./01-stakeholders-scope.md) · [Functional requirements](./03-functional-requirements.md) · [Acceptance criteria](./08-acceptance-mvp-future.md)

---

## 1. Project Overview

**We Check** replaces manual roll call—calling names and paper sign-in—with a responsive web and mobile-web check-in experience. Instructors open a live session, display a rotating QR code, and students check in from their phone browser using camera and GPS. The training office receives auditable attendance data and can export CSV for downstream academic systems.

| Attribute | Value |
| --- | --- |
| Product name | We Check |
| Domain | Digital attendance and session check-in for educational workshops and classes |
| Organization context | HESD workshop program and institutional training office (Phòng Đào Tạo) |
| Primary locale | Vietnamese (`vi-VN`) for user-facing copy |
| MVP cohort size | 100–150 participants per session |
| Delivery platform | Responsive web; mobile web for student check-in (no native app install) |
| Source inputs | [Initial idea](../initial-idea.md), [product metadata](../product-meta.json) |

The MVP targets recurring workshop cohorts where organizers currently lose 15–30 minutes per session to manual attendance, teaching is interrupted while roll call completes, and proxy check-in undermines data integrity for sponsors and training office reporting.

---

## 2. Business Context

### 2.1 Problem statement

HESD workshop organizers and instructors currently conduct attendance manually for 100–150 students per session. This process consumes 15–30 minutes of each session, delays instructional content, and provides no reliable identity verification. Students can check in on behalf of absent peers, producing attendance records that do not reflect actual participation. Training office staff must manually consolidate paper or spreadsheet data after each session, delaying reports to leadership and sponsors.

### 2.2 Affected users and impact

| User group | Current pain | Business impact |
| --- | --- | --- |
| Workshop organizers / Training Office Admin | Manual roll call coordination and post-session data consolidation | Delayed reporting; unreliable metrics for program evaluation |
| Instructors / Facilitators | Teaching interrupted while attendance completes | Reduced effective learning time per session |
| Students (100–150 per cohort) | Waiting during manual roll call; incentive to proxy check-in | Poor experience; inaccurate personal attendance history |

Without a digital check-in system, attendance data cannot scale with cohort size while maintaining speed and accuracy. Organizers cannot confidently report participation rates to sponsors or compare effectiveness across workshop iterations.

### 2.3 Root cause

The program lacks a purpose-built attendance system. The entire workflow depends on human verification (name calling, paper signatures) with no cryptographic or location-based controls. At 100–150 participants, manual methods exceed acceptable time and error thresholds for live workshop delivery.

### 2.4 Strategic alignment

We Check aligns with HESD goals to deliver professional, scalable workshop operations and with the training office need for exportable, auditable attendance records. The MVP prioritizes must-have check-in integrity (rotating QR, GPS verification, one check-in per account) before deep integration with legacy student information systems.

Cross-reference: stakeholder responsibilities and MVP boundaries are defined in [01-stakeholders-scope.md](./01-stakeholders-scope.md). End-to-end flows are specified in [02-business-workflow.md](./02-business-workflow.md).

---

## 3. Objectives

### 3.1 Vision

Build a reliable digital attendance system for HESD workshops that completes cohort check-in within minutes, verifies participant identity and presence, and gives organizers accurate reports without manual reconciliation.

### 3.2 Business objectives

| ID | Objective | User / business value | Metric | Target | Timeframe |
| --- | --- | --- | --- | --- | --- |
| OBJ-01 | Automate session check-in | Save organizer and instructor time; reduce manual errors | Time to complete check-in for full cohort | < 5 minutes | Each live session |
| OBJ-02 | Manage participant roster and verification | Organizers control registered vs. actual attendance per cohort | Identity verification success rate at check-in | ≥ 98% | Each workshop cohort |
| OBJ-03 | Enable attendance reporting and export | Training office evaluates program effectiveness and retains history | Time to produce attendance report after session ends | < 10 minutes | Each live session |

### 3.3 Success metrics

| ID | Goal | User / business value | Metric | Target | Timeframe |
| --- | --- | --- | --- | --- | --- |
| SM-01 | Check-in accuracy | Trustworthy attendance data without manual reconciliation | Successful check-ins / total present attendees | ≥ 99% | Each live session |
| SM-02 | System stability during live sessions | No disruption to workshop delivery | Downtime during active check-in window | 0 minutes | Each live session |
| SM-03 | Anti-proxy effectiveness | Deter proxy check-in via shared credentials or QR | Duplicate or spoof attempts correctly rejected | 100% of test scenarios in pilot | Before go-live |
| SM-04 | Privacy compliance baseline | Protect student location and identity data | GPS raw coordinates not persisted after verification; consent captured | Pass internal NĐ 13/2023 checklist | Before go-live |

### 3.4 MVP success criteria (summary)

The MVP is successful when a full HESD cohort (100–150 students) can check in via mobile web within five minutes, instructors see accurate real-time attendance, the training office exports CSV within ten minutes of session close, and zero unplanned downtime occurs during the live check-in window. Detailed acceptance tests are tracked under `AC-xx` in [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).

### 3.5 Constraints and assumptions (overview)

| Category | MVP default | Detail location |
| --- | --- | --- |
| GPS radius | 100 m from room coordinates; instructor-adjustable per session | [prompt.md](./prompt.md), [04-business-rules.md](./04-business-rules.md) |
| QR token lifetime | 30 seconds; no exceptions | [05-state-machine.md](./05-state-machine.md) |
| Authentication | Email/password or institutional account in MVP; SSO deferred | [01-stakeholders-scope.md](./01-stakeholders-scope.md) Future consideration |
| Roster source | Manual import or CSV if academic API unavailable | [01-stakeholders-scope.md](./01-stakeholders-scope.md) |
| Device support | iOS 15+ Safari, Android 10+ Chrome | [07-non-functional-risk.md](./07-non-functional-risk.md) |

---

## 4. Document map

| Document | Purpose |
| --- | --- |
| [00-project-overview.md](./00-project-overview.md) | Vision, context, objectives (this document) |
| [01-stakeholders-scope.md](./01-stakeholders-scope.md) | Stakeholders, in/out scope |
| [02-business-workflow.md](./02-business-workflow.md) | End-to-end business flows |
| [03-functional-requirements.md](./03-functional-requirements.md) | `FR-xx` functional requirements |
| [04-business-rules.md](./04-business-rules.md) | `BR-xx` business rules |
| [05-state-machine.md](./05-state-machine.md) | Session, attendance, and QR token states |
| [06-domain-model.md](./06-domain-model.md) | Entities and relationships |
| [07-non-functional-risk.md](./07-non-functional-risk.md) | `NFR-xx` quality attributes and risks |
| [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) | `AC-xx` acceptance criteria; MVP vs future |

When documents conflict, [prompt.md](./prompt.md) is the authoritative MVP scope reference.
