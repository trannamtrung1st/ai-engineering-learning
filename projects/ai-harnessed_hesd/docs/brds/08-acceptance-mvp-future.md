# Attendly — Acceptance Criteria, MVP, and Future Scope

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [01-stakeholders-scope.md](./01-stakeholders-scope.md) · [02-business-workflow.md](./02-business-workflow.md) · [03-functional-requirements.md](./03-functional-requirements.md) · [04-business-rules.md](./04-business-rules.md) · [05-state-machine.md](./05-state-machine.md) · [07-non-functional-risk.md](./07-non-functional-risk.md)

---

## 1. Purpose and acceptance approach

This document defines testable acceptance criteria (`AC-xx`) for Attendly MVP, then separates MVP commitments from future enhancements.

### 1.1 Acceptance principles

| Principle | Rule |
| --- | --- |
| Traceability | Every acceptance criterion maps to one or more `FR-xx` and relevant `BR-xx` |
| Testability | Criteria are written in Given/When/Then format |
| MVP discipline | Core launch criteria are mandatory; future items are explicitly excluded |
| Measurability | Non-functional gates align with [07-non-functional-risk.md](./07-non-functional-risk.md) |

---

## 2. MVP acceptance criteria

### 2.1 Session lifecycle and QR behavior

#### AC-01 — Open attendance for scheduled session

**Given** a lecturer is assigned to a class section and a class session is in `Scheduled` state,  
**When** the lecturer opens attendance,  
**Then** the session transitions to `Open`, `openedAt`/actor are recorded, and QR display starts rotating.  
Trace: `FR-07`, `FR-11` · `BR-01`.

#### AC-02 — QR token rotates with 30-second TTL

**Given** a class session is `Open`,  
**When** QR tokens are issued,  
**Then** each token is valid for 30 seconds and the display refreshes to a new valid token without lecturer reload.  
Trace: `FR-11`, `FR-14` · `BR-03`.

#### AC-03 — Multi-use token within TTL

**Given** one valid QR token for an open session,  
**When** multiple enrolled students submit check-in with that token before expiry,  
**Then** the system processes each student independently and does not reject solely because another student already used the same token.  
Trace: `FR-12` · `BR-03`.

#### AC-04 — Expired or wrong-session token rejected

**Given** a token is expired or bound to a different session,  
**When** a student submits check-in,  
**Then** the request is rejected with a structured reason (`ExpiredQr` or invalid-session equivalent) and a failed attempt is logged.  
Trace: `FR-13`, `FR-22` · `BR-03`, `BR-04`, `BR-23`.

#### AC-05 — Session close blocks self check-in

**Given** a class session transitions to `Closed`,  
**When** a student attempts check-in,  
**Then** the attempt is rejected with `SessionClosed` and no new successful attendance record is created.  
Trace: `FR-08` · `BR-02`.

### 2.2 Student identity and eligibility

#### AC-06 — Login gate enforced

**Given** a student opens check-in URL without authenticated session,  
**When** they attempt to proceed,  
**Then** the system redirects to login and only allows submission after successful authentication.  
Trace: `FR-15`, `FR-36` · `BR-05`.

#### AC-07 — Enrollment validation enforced

**Given** a student account is not actively enrolled in the target class section,  
**When** they submit check-in,  
**Then** the system rejects with `NotEnrolled`, logs the attempt, and does not create a success attendance state.  
Trace: `FR-17`, `FR-22` · `BR-06`, `BR-23`.

#### AC-08 — One successful check-in per student per session

**Given** a student already has a successful attendance result for a session,  
**When** the student submits another check-in attempt for the same session,  
**Then** the system rejects with `DuplicateCheckIn` and preserves the original successful attendance record.  
Trace: `FR-18` · `BR-07`.

### 2.3 GPS and policy-aware validation (MVP Should gate)

#### AC-09 — GPS-required policy rejection path

**Given** effective policy requires GPS for the session,  
**When** student location permission is denied or unavailable,  
**Then** self check-in is rejected with `GpsDisabled`/`GpsRequired`, and lecturer manual fallback remains available.  
Trace: `FR-34`, `FR-35`, `FR-20` · `BR-08`, `BR-14`.

#### AC-10 — Out-of-radius handling

**Given** policy requires GPS and room coordinates are configured,  
**When** submitted location is outside configured radius,  
**Then** the system rejects or flags according to policy and logs distance/validation metadata for review.  
Trace: `FR-35`, `FR-22` · `BR-09`, `BR-10`, `BR-23`.

### 2.4 Attendance outcomes and manual fallback

#### AC-11 — Present vs Late assignment

**Given** all validation checks pass for an open session,  
**When** check-in occurs within present window or late window,  
**Then** attendance status is recorded as `Present` or `Late` respectively with timestamp and QR method.  
Trace: `FR-23` · `BR-11`, `BR-12`.

#### AC-12 — Auto-absent at close

**Given** a session closes and an enrolled student has no successful attendance result,  
**When** close processing runs,  
**Then** the student is assigned `Absent` unless already `Excused` or manually resolved.  
Trace: `FR-09` · `BR-13`.

#### AC-13 — Lecturer manual correction within policy window

**Given** lecturer is assigned to the section and within manual edit window,  
**When** lecturer updates attendance status with required reason,  
**Then** the update is applied and full audit data (actor/time/old/new/reason) is recorded.  
Trace: `FR-20`, `FR-29` · `BR-14`, `BR-22`.

#### AC-14 — Lecturer manual correction after window is blocked or escalated

**Given** lecturer attempts correction after edit window expiration,  
**When** update is submitted,  
**Then** the system rejects or routes to admin override path according to policy.  
Trace: `FR-20`, `FR-21` · `BR-15`, `BR-16`.

### 2.5 Reporting, export, and access boundaries

#### AC-15 — Lecturer export scope restriction

**Given** a lecturer requests attendance export,  
**When** export is generated,  
**Then** output includes only assigned class sections and excludes other sections by default.  
Trace: `FR-27` · `BR-18`.

#### AC-16 — Unauthorized report/export denied

**Given** a user lacks scope for a report or export request,  
**When** they access the feature,  
**Then** the system denies access without disclosing restricted data.  
Trace: `FR-27`, `FR-28`, `FR-32` · `BR-19`.

#### AC-17 — Export audit coverage

**Given** any successful export action,  
**When** export completes,  
**Then** an audit log entry is written with actor, timestamp, scope, and format.  
Trace: `FR-30` · `BR-18`, `BR-22`.

### 2.6 Auditability and observability

#### AC-18 — Failed check-in reason code coverage

**Given** any failed check-in attempt,  
**When** processing completes,  
**Then** a `CheckInAttempt` record exists with structured failure outcome code and timestamp.  
Trace: `FR-22` · `BR-23`.

#### AC-19 — Manual edit audit completeness

**Given** any attendance status mutation by lecturer/admin/system process,  
**When** mutation is committed,  
**Then** corresponding audit record is present and queryable.  
Trace: `FR-29` · `BR-22`.

### 2.7 Non-functional MVP gates

#### AC-20 — Median check-in time gate

**Given** representative pilot load,  
**When** check-in metrics are measured across class sessions,  
**Then** median student check-in time is below 30 seconds.  
Trace: `NFR-01` in [07-non-functional-risk.md](./07-non-functional-risk.md).

#### AC-21 — 5-minute completion gate

**Given** representative enrolled class sections,  
**When** attendance opens,  
**Then** majority of enrolled students complete check-in within 5 minutes.  
Trace: `NFR-02` in [07-non-functional-risk.md](./07-non-functional-risk.md).

#### AC-22 — Processing success gate

**Given** valid check-in requests under expected campus load,  
**When** processing results are aggregated,  
**Then** valid check-in processing success rate meets or exceeds 99%.  
Trace: `NFR-03` in [07-non-functional-risk.md](./07-non-functional-risk.md).

#### AC-23 — Security and scope gate

**Given** role-based test scenarios for student, lecturer, department admin, academic admin, IT admin, and system auditor,  
**When** protected routes and export operations are tested,  
**Then** only authorized scope is accessible and unauthorized access is denied.  
Trace: `NFR-09`, `NFR-10`.

#### AC-24 — Privacy minimization gate

**Given** GPS-enabled sessions and retention jobs,  
**When** data storage and lifecycle are reviewed,  
**Then** GPS is captured only at check-in events and raw coordinates follow bounded retention policy.  
Trace: `NFR-11`, `NFR-12`.

#### AC-25 — Manual fallback operability gate

**Given** classroom scenarios with device/network/GPS failure,  
**When** lecturer applies manual fallback,  
**Then** attendance can be resolved without bypassing audit requirements and without broadening unauthorized access.  
Trace: `NFR-17`, `FR-20`, `BR-14`.

---

## 3. MVP scope commitment

### 3.1 MVP in-scope (release blocking)

| Scope area | Commitment |
| --- | --- |
| Core session flow | Session open/close with rotating 30s QR and state-safe behavior |
| Student check-in | Mobile-web scan, login gate, enrollment check, duplicate prevention |
| Attendance outcomes | `Present`, `Late`, `Absent`, `Manual Present` with policy-aware close behavior |
| Lecturer operations | Realtime roster and manual correction within policy window |
| Compliance baseline | CSV export with strict role scope and full audit logging |
| Data trust | Failed attempt reason codes and immutable correction trail |

### 3.2 MVP conditional scope (ship if schedule allows)

| Area | Condition for MVP inclusion |
| --- | --- |
| GPS validation | GPS policy configuration, radius checks, and rejection/flag flows stable in pilot |
| Extended statuses | `Excused`/`Suspicious` fully integrated in reporting and workflow |
| Department admin and system auditor views | Scope model validated with institutions using faculty-level governance |
| Absence threshold alerts | Alert rules verified to avoid noisy false alarms |

### 3.3 Explicit MVP exclusions

Attendly MVP excludes:

- Facial recognition and biometric verification.
- Native mobile apps.
- Absolute GPS anti-spoofing guarantees.
- Continuous location tracking outside check-in.
- Tuition, exam scheduling, grading, and LMS replacement scope.
- Deep real-time two-way integration with legacy SIS as launch dependency.

Source alignment: [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.3 · [prompt.md](./prompt.md) §2.3.

---

## 4. Release readiness checklist

### 4.1 Functional readiness

- `AC-01` through `AC-19` pass in staging with production-like data.
- Key role personas complete end-to-end UAT without unresolved blockers.
- Rejection reason codes are visible and localized for student-facing errors.

### 4.2 Non-functional readiness

- `AC-20` through `AC-25` meet thresholds from [07-non-functional-risk.md](./07-non-functional-risk.md).
- Peak class-start load test results documented and approved.
- Incident response and manual fallback runbooks are available to campus support.

### 4.3 Governance readiness

- Audit queries for disputes are validated by academic operations.
- Data retention policy for attendance and GPS artifacts is approved.
- Permission matrix is signed off by academic admin and IT admin owners.

---

## 5. Post-MVP phases

### 5.1 Phase 2 — Policy and reporting expansion

Primary outcomes:

- Full policy hierarchy tooling with effective-policy explainability.
- Absence threshold alerts with controlled notification rules.
- Extended reporting by term/course/faculty and richer filtering.
- Broader department admin and auditor workflows.

Acceptance direction:

- Policy precedence correctness and report accuracy across large datasets.
- Alert precision/recall tuning to reduce operational noise.

### 5.2 Phase 3 — Integration and hardening

Primary outcomes:

- SSO/MFA integration.
- SIS/API synchronization for roster and timetable.
- Enhanced operational monitoring, security hardening, and DR practices.

Acceptance direction:

- Identity federation reliability.
- Sync reconciliation SLAs and conflict handling.

### 5.3 Phase 4 — Advanced anti-fraud (optional)

Primary outcomes:

- Device binding, random reverification, and advanced anomaly detection.
- Optional higher-assurance verification models where policy/legal context permits.

Acceptance direction:

- Fraud-reduction efficacy measured against baseline without harming classroom usability.

---

## 6. Future consideration

Potential roadmap candidates beyond committed phases:

- Intelligent dispute triage and evidence package generation.
- Privacy automation for data deletion and retention audits.
- Advanced cross-campus analytics for attendance trend prediction.
- API/webhook ecosystem for external academic platforms.

All future items remain non-blocking for MVP launch.

---

## 7. Traceability index

| Acceptance group | Primary FR links | Primary BR links | NFR links |
| --- | --- | --- | --- |
| Session and QR (`AC-01` to `AC-05`) | `FR-07` to `FR-14` | `BR-01` to `BR-04` | `NFR-06`, `NFR-07` |
| Student validation (`AC-06` to `AC-10`) | `FR-15`, `FR-17`, `FR-18`, `FR-34`, `FR-35` | `BR-05` to `BR-10` | `NFR-11`, `NFR-14` |
| Attendance and fallback (`AC-11` to `AC-14`) | `FR-09`, `FR-20`, `FR-21`, `FR-23` | `BR-11` to `BR-16` | `NFR-17` |
| Access/export/audit (`AC-15` to `AC-19`) | `FR-22`, `FR-27`, `FR-29`, `FR-30`, `FR-32` | `BR-18`, `BR-19`, `BR-22`, `BR-23` | `NFR-09`, `NFR-10`, `NFR-13` |
| NFR release gates (`AC-20` to `AC-25`) | Cross-functional | Cross-rule | `NFR-01` to `NFR-17` |
