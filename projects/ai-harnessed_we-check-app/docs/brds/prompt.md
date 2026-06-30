# We Check — MVP BRD and UI Design Prompt

Condensed product brief for generating Business Requirements Documents and UI/UX specifications. Source: [initial idea](../initial-idea.md), [product metadata](../product-meta.json).

---

## 1. Product Goal

**We Check** is a web and mobile-web digital attendance system for the Harness Engineering for Software Development (HESD) workshop program and institutional training office operations. It replaces manual roll call (calling names, paper sign-in) for cohorts of **100–150 participants per session** with rotating QR check-in, GPS verification, and attendance reporting.

| Dimension | Target |
| --- | --- |
| Domain | Digital attendance and session check-in for educational workshops and classes |
| Locale | Vietnamese (`vi-VN`) UI copy; technical docs may use English identifiers |
| Check-in completion | Entire cohort checked in within **5 minutes** per session |
| Report export | Attendance report available within **10 minutes** after session ends |
| Identity verification success rate | ≥ 98% per workshop cohort |
| Successful check-in rate | ≥ 99% of present attendees |
| Session downtime | **0 minutes** during live workshops |

**Problem to solve:** Manual attendance consumes 15–30 minutes per session, interrupts teaching, lacks identity verification (proxy check-in), and produces unreliable data for sponsors and training office reporting.

**Primary value:** Organizers gain accurate, auditable attendance in minutes; students check in via phone browser without installing an app; instructors see real-time attendance and can handle exceptions.

---

## 2. MVP Scope

### 2.1 In scope (Must)

| Capability | MVP behavior |
| --- | --- |
| Session creation and management | Instructor creates a session linked to class/subject, sets room GPS coordinates, optional GPS radius override (default **100 m** from room), opens/closes live check-in window |
| Rotating dynamic QR (30 s) | Server issues short-lived QR tokens; display refreshes every 30 seconds; expired tokens rejected with clear user message |
| Mobile web QR scan | Student uses phone browser camera; no native app install |
| GPS location verification | Compare device coordinates to session room; reject if outside configured radius; reject if GPS disabled or permission denied |
| Anti-proxy check-in | One successful check-in per student account per session; one-time-use QR token per successful scan; duplicate attempts return conflict |
| Anti-GPS-spoofing (baseline) | Log suspicious location requests; detect obvious mock-location signals where platform APIs allow; instructor manual override for edge cases |
| Authentication | Valid login required before check-in; unauthenticated users redirected to login |
| Instructor manual attendance edit | Instructor may correct attendance during session and up to **24 hours** after close; changes audit-logged |
| Attendance reporting | Per-class and per-subject views for assigned instructor; training office admin sees institution-wide |
| CSV export | Role-scoped: instructor exports within assigned class-subject pairs; training office admin institution-wide; student denied ([BR-09](./04-business-rules.md)) |
| First admin bootstrap | When `User.count = 0`, `/setup` creates first `TrainingOfficeAdmin`; one-time per deployment |
| Manual class and subject management | Admin creates class/subject reference records before CSV roster import |
| QR preflight gate | Server validates token, session, enrollment before student enters GPS step |
| Permission-gated navigation and role hubs | Nav chrome and hub cards filtered by permission; role-specific home after login |
| Route discovery on unauthenticated home | `/` shows quick links to login and role entry routes; no URL memorization for workshop testers |
| Device API fidelity | Production uses real camera/GPS; simulation opt-in via `VITE_ENABLE_DEVICE_SIMULATION` |
| GPS ready-state UX | No spinner when coordinates ready; check icon + enabled submit |

### 2.2 In scope (Should — include if schedule allows)

- Automatic absence warning when student exceeds **20%** unexcused absences for a subject
- Real-time attendance dashboard for instructor during active session
- Quick-start onboarding copy for camera and GPS permissions

### 2.3 Out of scope (MVP)

- Facial recognition
- Tuition payment
- Exam schedule management
- Deep integration with legacy student information systems (MVP uses manual roster import or CSV if API unavailable)
- Native iOS/Android apps
- Offline check-in queue (retry on poor network only)

### 2.4 Future consideration

- SSO / campus identity provider integration
- WiFi BSSID verification for indoor accuracy
- Two-factor authentication for high-risk accounts
- PIN-based fallback when device battery dies
- Auto-scaling load tests beyond pilot scale
- Long-term GPS retention policies beyond verification window

---

## 3. Roles

| Role | Actor label | Primary responsibilities | MVP access |
| --- | --- | --- | --- |
| Student | `Student` | Scan QR, grant camera/GPS, view personal attendance history | Own attendance only |
| Instructor | `Instructor` | Create/open/close sessions, display QR, monitor live attendance, manual corrections, class/subject reports | Sessions and rosters they own |
| Training Office Admin | `TrainingOfficeAdmin` | System-wide policy, user provisioning, all reports, institution-wide CSV export | Full read; institution-wide export; user admin |
| IT Operations | `ITOperations` | Hosting, uptime, incident response | No in-app business UI in MVP; operational runbooks only |

**Decision authority:** Training office defines attendance policy thresholds; instructors operationalize per session; students consume check-in flows only.

Cross-reference: full stakeholder detail belongs in [01-stakeholders-scope.md](./01-stakeholders-scope.md).

---

## 4. Canonical States

Downstream BRD and UI docs must use these state names consistently.

### 4.1 Session lifecycle

| State | Meaning | Allowed transitions |
| --- | --- | --- |
| `Draft` | Session created; room GPS configured; not yet open for check-in | → `Active`, → `Cancelled` |
| `Active` | QR displayed; students may check in within attendance window | → `Closed` |
| `Closed` | Check-in window ended; roster frozen except manual edits within policy | → (terminal for MVP) |
| `Cancelled` | Session abandoned before or during setup | (terminal) |

**Attendance window:** From session open until **10 minutes** after scheduled start; late scans mark `Absent` unless instructor extends manually.

### 4.2 Attendance record (per student per session)

| State | Meaning |
| --- | --- |
| `Pending` | Enrolled; no successful check-in yet while session is `Active` |
| `Present` | Successful QR + GPS + auth verification |
| `Absent` | Window closed without check-in, or explicit late rejection |
| `Excused` | Instructor or admin marked excused absence (excluded from absence-rate warnings when policy applies) |
| `Rejected` | Attempt failed (expired QR, out of radius, duplicate, spoof suspicion) — may transition to `Present` via manual override |

### 4.3 QR token

| State | Meaning |
| --- | --- |
| `Valid` | Issued, within 30 s window, not yet consumed |
| `Expired` | Past 30 s from issue time |
| `Consumed` | Successfully used for one check-in |

### 4.4 Check-in attempt outcome (API/UI)

`Success` | `ExpiredQr` | `OutOfRadius` | `DuplicateCheckIn` | `GpsDisabled` | `Unauthenticated` | `SessionNotActive` | `SpoofSuspected`

State diagrams: [05-state-machine.md](./05-state-machine.md).

---

## 5. Output Rules

Documents produced from this prompt must follow these conventions.

### 5.1 Document set and numbering

| File | Purpose |
| --- | --- |
| [00-project-overview.md](./00-project-overview.md) | Vision, objectives, metrics |
| [01-stakeholders-scope.md](./01-stakeholders-scope.md) | Stakeholders, in/out scope |
| [02-business-workflow.md](./02-business-workflow.md) | End-to-end flows |
| [03-functional-requirements.md](./03-functional-requirements.md) | `FR-xx` requirements |
| [04-business-rules.md](./04-business-rules.md) | `BR-xx` rules |
| [05-state-machine.md](./05-state-machine.md) | State transitions |
| [06-domain-model.md](./06-domain-model.md) | Entities and relationships |
| [07-non-functional-risk.md](./07-non-functional-risk.md) | `NFR-xx`, risks |
| [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) | `AC-xx`, MVP vs future |

### 5.2 Requirement ID formats

- **Functional:** `FR-01`, `FR-02`, … — each with Actor, Behavior, and trace to capabilities above
- **Business rules:** `BR-01`, … — condition, trigger, outcome, exceptions
- **Non-functional:** `NFR-01`, … — measurable quality attributes
- **Acceptance:** `AC-01`, … — testable Given/When/Then criteria tied to `FR-xx`

IDs must be unique across the BRD set.

### 5.3 Writing standards

- Use numbered markdown sections (`## 1.`, `### 1.1`)
- Product name **We Check** in user-facing references
- MVP-only in main body; defer enhancements to **Future consideration**
- No ambiguous placeholders; resolve open questions with explicit MVP defaults (e.g., GPS radius **100 m** default, instructor-adjustable per session)
- Cross-link related sections by filename and requirement ID
- Privacy: GPS used only for verification; do not persist raw coordinates after successful validation; comply with Vietnam personal data protection expectations (NĐ 13/2023 alignment in NFR docs)
- Platform: responsive web; test targets iOS 15+ Safari and Android 10+ Chrome

### 5.4 UI/UX derivation

UI specs under `docs/ui-ux/` must map pages and flows to `FR-xx` and `AC-xx`, prioritize mobile-first check-in, instructor projection-friendly QR display, and clear permission-denied recovery paths. Reference this prompt for scope boundaries before adding screens.

### 5.5 Key business rules to preserve in BR-xx

- QR token validity: **30 seconds**; no exceptions
- One check-in per student account per session
- One-time-use token consumption
- GPS required; no check-in without location permission
- Session cannot go `Active` without valid room coordinates
- CSV export scoped by role: instructor within assigned class-subject; admin institution-wide; student denied ([BR-09](./04-business-rules.md))
- Manual attendance edits audit-logged; instructor edit window **24 hours** post-close unless admin overrides

---

*This prompt is the single source of truth for MVP scope when BRD and UI documents conflict with the initial idea draft.*
