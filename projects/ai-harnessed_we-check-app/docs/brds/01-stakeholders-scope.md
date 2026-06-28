# We Check — Stakeholders and Scope

Stakeholder register, decision authority, and MVP scope boundaries for **We Check**. Defines who participates in the attendance system, what they need, and what the first release includes and excludes.

**Related documents:** [Project overview](./00-project-overview.md) · [MVP BRD prompt](./prompt.md) · [Business workflow](./02-business-workflow.md) · [Functional requirements](./03-functional-requirements.md) · [Roles and permissions (technical)](../technical/01-roles-permissions.md)

---

## 1. Stakeholders

### 1.1 Stakeholder register

| Role | Actor label | Responsibility | Decision authority | Needs and concerns | MVP involvement |
| --- | --- | --- | --- | --- | --- |
| Student | `Student` | Scan rotating QR via mobile browser; grant camera and GPS permissions; view personal attendance history | None — consumes check-in flow only | Fast check-in (< 30 s per person); clear error messages when QR expires or GPS denied; privacy of location data | End user — every live session |
| Instructor / Facilitator | `Instructor` | Create and open sessions; configure room GPS and optional radius; display QR for cohort; monitor live attendance; manually correct exceptions; view class/subject reports | Operational — per-session attendance window, manual overrides within 24 hours post-close | Simple session setup; projection-friendly QR display; real-time roster view; audit trail on manual edits | Primary operator — every live session |
| Training Office Admin | `TrainingOfficeAdmin` | System-wide policy (absence thresholds); user provisioning for instructors and students; institution-wide reports; CSV export for academic systems | Policy and data export — defines absence rules; sole CSV export authority | Accurate aggregate data; export within 10 minutes; RBAC enforcement; compliance with NĐ 13/2023 | Administrator — setup, periodic review, export |
| IT Operations | `ITOperations` | Host infrastructure; ensure uptime; incident response; security patching | Infrastructure — hosting, monitoring, backup | Zero downtime during live workshops; hosting within Vietnam; TLS and encryption standards | Background — no in-app business UI in MVP |

### 1.2 Stakeholder needs summary

**Students** need a frictionless mobile web flow: open link or scan QR, authenticate once per session if needed, grant permissions with guided copy in Vietnamese, and receive immediate confirmation or actionable rejection (expired QR, out of radius, already checked in).

**Instructors** need to start a session in under two minutes, see who has checked in during the attendance window, and resolve edge cases (no smartphone, GPS failure, late arrival) through manual status edits that are audit-logged.

**Training Office Admin** needs centralized control over user accounts, attendance policy configuration, cross-cohort visibility, and CSV export restricted to their role. They require confidence that GPS coordinates are used only for verification and not stored long-term.

**IT Operations** needs deployable web stack, health monitoring, and runbooks. MVP does not require in-application IT dashboards; operational concerns are captured in [07-non-functional-risk.md](./07-non-functional-risk.md).

### 1.3 Decision authority matrix

| Decision area | Primary authority | Consulted | Informed |
| --- | --- | --- | --- |
| Attendance policy (absence threshold, excused absence rules) | Training Office Admin | Instructors | Students |
| Per-session GPS radius and room coordinates | Instructor | Training Office Admin | IT Operations |
| Session open/close and manual attendance corrections | Instructor | — | Training Office Admin |
| CSV export and bulk data access | Training Office Admin | IT Operations | Instructors |
| Infrastructure and security controls | IT Operations | Training Office Admin | Instructors |

### 1.4 Communication and escalation

During live workshops, instructors resolve check-in exceptions at the session level. Issues affecting system availability escalate to IT Operations. Data disputes or policy exceptions escalate to Training Office Admin. Privacy or legal questions route to training office leadership with IT Operations support.

Role-to-permission mapping for implementation: [01-roles-permissions.md](../technical/01-roles-permissions.md) (technical phase).

---

## 2. Scope

MVP scope follows [prompt.md](./prompt.md). Capabilities marked **Must** are required for release; **Should** items ship if schedule allows without delaying Must capabilities.

### 2.1 In scope

#### 2.1.1 Must — required for MVP release

| Capability | MVP behavior | Primary actor |
| --- | --- | --- |
| Session creation and management | Instructor creates session linked to class/subject, sets room GPS coordinates, optional GPS radius override (default **100 m**), opens and closes live check-in window | `Instructor` |
| Rotating dynamic QR (30 s) | Server issues short-lived tokens; display refreshes every 30 seconds; expired tokens rejected with user-visible message | `Instructor`, `Student` |
| Mobile web QR scan | Student uses phone browser camera; no native app install | `Student` |
| GPS location verification | Compare device coordinates to session room; reject if outside configured radius; reject if GPS disabled or permission denied | `Student` |
| Anti-proxy check-in | One successful check-in per student account per session; one-time-use QR token per successful scan; duplicate attempts return conflict | `Student`, `Instructor` |
| Anti-GPS-spoofing (baseline) | Log suspicious location requests; detect obvious mock-location signals where platform APIs allow; instructor manual override for edge cases | `Student`, `Instructor` |
| Authentication | Valid login required before check-in; unauthenticated users redirected to login | All authenticated roles |
| Instructor manual attendance edit | Instructor corrects attendance during session and up to **24 hours** after close; all changes audit-logged | `Instructor` |
| Attendance reporting | Per-class and per-subject views for assigned instructor; training office admin sees institution-wide | `Instructor`, `TrainingOfficeAdmin` |
| CSV export | Training office admin only; export attendance data for downstream academic systems | `TrainingOfficeAdmin` |
| Roster management (baseline) | Import or maintain participant list per class via admin UI or CSV upload when academic API is unavailable | `TrainingOfficeAdmin`, `Instructor` |

#### 2.1.2 Should — include if schedule allows

| Capability | MVP behavior | Primary actor |
| --- | --- | --- |
| Automatic absence warning | Notify student and instructor when unexcused absences exceed **20%** of completed sessions for a subject | `TrainingOfficeAdmin`, `Instructor` |
| Real-time attendance dashboard | Live count and roster status during active session | `Instructor` |
| Permission onboarding copy | In-app Vietnamese guidance for camera and GPS permission grants on first check-in | `Student` |

#### 2.1.3 Platform and compliance (in scope)

- Responsive web application; student check-in optimized for mobile web (iOS 15+ Safari, Android 10+ Chrome).
- Vietnamese (`vi-VN`) user-facing strings.
- GPS used only for presence verification; raw coordinates not persisted after successful validation.
- Consent capture for location processing aligned with NĐ 13/2023 expectations (detailed in [07-non-functional-risk.md](./07-non-functional-risk.md)).
- Instructor fallback: manual attendance entry when student cannot complete digital check-in (no suitable device, dead battery, denied permissions).

### 2.2 Out of scope

The following are explicitly **excluded from MVP**. They may be reconsidered under Future consideration (Section 2.3).

| Item | Rationale |
| --- | --- |
| Facial recognition | High cost, privacy review, and hardware variance; not required for workshop-scale MVP |
| Tuition payment | Unrelated to attendance check-in domain |
| Exam schedule management | Separate academic module; no dependency for HESD workshop attendance |
| Deep integration with legacy student information systems | MVP uses manual roster import or CSV; API integration deferred until data contract confirmed with IT |
| Native iOS / Android applications | Mobile web meets MVP install-free requirement |
| Offline check-in queue | MVP supports network retry only; full offline sync adds complexity beyond pilot need |
| WiFi BSSID indoor verification | Enhancement for GPS accuracy; baseline GPS radius sufficient for MVP pilot |
| Two-factor authentication | Recommended for production hardening; not blocking for controlled pilot cohort |
| Long-term GPS coordinate retention | Contradicts privacy baseline; verification-only storage in MVP |

### 2.3 Future consideration

Items below are valuable but deferred until MVP validates core check-in flows with HESD pilot cohorts.

| Item | Trigger to prioritize |
| --- | --- |
| SSO / campus identity provider integration | Confirmed availability from IT Operations before scale-out |
| WiFi BSSID verification for indoor accuracy | Pilot shows unacceptable GPS false positives in large or multi-floor rooms |
| Two-factor authentication for high-risk accounts | Security review or sponsor requirement post-pilot |
| PIN-based fallback when device battery dies | Pilot feedback shows manual override volume is unsustainable |
| Auto-scaling load tests beyond pilot scale (500+ concurrent) | Program expands to multiple simultaneous sessions institution-wide |
| Academic system API integration | Data sharing agreement and API specification finalized with IT |
| Advanced anti-spoofing (device attestation, behavioral signals) | Baseline spoof detection insufficient in pilot metrics |
| Multi-language UI beyond Vietnamese | Program expands to non-Vietnamese cohorts |

### 2.4 Scope dependencies

| Dependency | Owner | MVP mitigation |
| --- | --- | --- |
| Room GPS coordinates for each session venue | Instructor | Required before session can go `Active`; blocked with clear message if missing ([BR-07](./04-business-rules.md)) |
| Student smartphone with camera and GPS | Student | Instructor manual attendance fallback |
| Network connectivity during check-in | Student / IT Operations | Client retry up to 3 attempts within 30 seconds; instructor fallback |
| Roster data (names, student IDs, class enrollment) | Training Office Admin | CSV import if academic API unavailable |
| Hosting within Vietnam | IT Operations | Select domestic cloud provider before infrastructure design |

### 2.5 Traceability to downstream artifacts

| Scope item | Follow-on document |
| --- | --- |
| Session and check-in flows | [02-business-workflow.md](./02-business-workflow.md) |
| Implementable requirements | [03-functional-requirements.md](./03-functional-requirements.md) (`FR-xx`) |
| Enforceable rules | [04-business-rules.md](./04-business-rules.md) (`BR-xx`) |
| Testable MVP criteria | [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) (`AC-xx`) |
| UI pages and flows | [docs/ui-ux/](../ui-ux/) (generated in UI/UX phase) |

When [initial idea](../initial-idea.md) and this document differ, [prompt.md](./prompt.md) and this scope section govern MVP delivery.
