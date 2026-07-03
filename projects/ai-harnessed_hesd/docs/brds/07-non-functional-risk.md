# Attendly — Non-Functional Requirements and Risk

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-project-overview.md](./00-project-overview.md) · [03-functional-requirements.md](./03-functional-requirements.md) · [04-business-rules.md](./04-business-rules.md) · [05-state-machine.md](./05-state-machine.md) · [06-domain-model.md](./06-domain-model.md) · [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md)

---

## 1. Purpose and quality scope

This document defines measurable non-functional requirements (`NFR-xx`) and the MVP risk model for Attendly.  
Quality expectations are calibrated for campus attendance operations where peak usage happens in short, predictable class-session windows.

### 1.1 Quality objectives

| Objective | Why it matters |
| --- | --- |
| Fast check-in at class start | Protect class time and reduce manual roll-call overhead |
| Reliable attendance processing | Avoid wrongful absence and dispute volume |
| Strong auditability | Support compliance, appeals, and forensic review |
| Privacy-by-design | Minimize sensitive data exposure, especially location data |
| Operational resilience | Maintain service during synchronized session peaks |

---

## 2. Non-functional requirements

### 2.1 Performance and scalability

#### NFR-01 — Student check-in latency

The system shall support a **median end-to-end student check-in time < 30 seconds** from QR scan to success result under normal campus network conditions.  
Trace: [00-project-overview.md](./00-project-overview.md) (`OBJ-01`) · [03-functional-requirements.md](./03-functional-requirements.md) (`FR-16`, `FR-23`).

#### NFR-02 — Classroom completion time

The system shall support completion of check-in for the majority of enrolled students in a class section within **5 minutes** of attendance window opening.  
Trace: [00-project-overview.md](./00-project-overview.md) (`OBJ-01`) · [02-business-workflow.md](./02-business-workflow.md).

#### NFR-03 — Processing success rate

For requests that satisfy session-open, token, enrollment, authentication, and policy preconditions, the system shall achieve **>= 99% valid check-in processing success**.  
Trace: [00-project-overview.md](./00-project-overview.md) §3.2 · [04-business-rules.md](./04-business-rules.md) (`BR-01` to `BR-12`).

#### NFR-04 — Concurrent class handling

The platform shall support concurrent check-in peaks across multiple open class sessions without violating `NFR-01` and `NFR-03`, using horizontal scaling and queue-safe/idempotent request handling.  
Trace: [06-domain-model.md](./06-domain-model.md) §9 · [03-functional-requirements.md](./03-functional-requirements.md) (`FR-22`).

### 2.2 Availability and reliability

#### NFR-05 — Availability during school hours

Attendly shall meet institution-approved uptime targets during school operating hours, with explicit maintenance windows communicated to administrators.  
Trace: [00-project-overview.md](./00-project-overview.md) §3.2.

#### NFR-06 — Consistent state transitions

Session state transitions (`Scheduled`, `Open`, `Closed`, `Cancelled`) and token states (`Valid`, `Expired`, `Invalid`) shall remain consistent and auditable, including under retry and timeout scenarios.  
Trace: [05-state-machine.md](./05-state-machine.md) §2, §4.

#### NFR-07 — Idempotent check-in behavior

Repeated or retried submissions from the same student/session shall not create duplicate successful attendance records; at most one successful record exists per (`studentId`, `classSessionId`).  
Trace: [04-business-rules.md](./04-business-rules.md) (`BR-07`) · [06-domain-model.md](./06-domain-model.md) (`AttendanceRecord` uniqueness).

### 2.3 Security and access control

#### NFR-08 — Secure transport

All browser, API, and export traffic shall use TLS (`HTTPS`) with modern cipher configuration; plaintext transport is disallowed in production.  
Trace: [initial-idea.md](../initial-idea.md) §16.

#### NFR-09 — Role-scoped authorization

Attendance data access shall be enforced by role and scope (student self-only, lecturer assigned sections, admin authorized scope), with deny-by-default behavior for unauthorized report/export requests.  
Trace: [03-functional-requirements.md](./03-functional-requirements.md) (`FR-27`, `FR-32`) · [04-business-rules.md](./04-business-rules.md) (`BR-18`, `BR-19`).

#### NFR-10 — Protected mutation path

Attendance mutations shall require authenticated authorized actors and produce immutable audit records including actor, timestamp, old/new values, and reason where required.  
Trace: [03-functional-requirements.md](./03-functional-requirements.md) (`FR-29`, `FR-30`) · [04-business-rules.md](./04-business-rules.md) (`BR-22`).

### 2.4 Privacy and data governance

#### NFR-11 — Data minimization for location

GPS data shall be collected only at check-in attempt time when policy requires location validation; continuous location tracking is prohibited in MVP.  
Trace: [01-stakeholders-scope.md](./01-stakeholders-scope.md) §2.3 · [03-functional-requirements.md](./03-functional-requirements.md) (`FR-34`).

#### NFR-12 — Limited retention of raw location data

Raw latitude/longitude shall be retained only for a bounded dispute-review window defined by policy; longer-term storage should prefer derived validation fields (pass/fail, distance range, accuracy range).  
Trace: [06-domain-model.md](./06-domain-model.md) (`CheckInAttempt`) · [initial-idea.md](../initial-idea.md) §15.

#### NFR-13 — Audit completeness

The system shall log **100%** of failed check-in attempts, manual attendance edits, and export actions with structured reason/context fields.  
Trace: [00-project-overview.md](./00-project-overview.md) §3.2 · [04-business-rules.md](./04-business-rules.md) (`BR-23`, `BR-22`, `BR-18`).

### 2.5 Usability and accessibility

#### NFR-14 — Mobile-first check-in UX

Student check-in interfaces shall be optimized for mobile web (iOS Safari, Android Chrome) with concise Vietnamese guidance for expired QR, login required, GPS denied, out-of-radius, and duplicate attempts.  
Trace: [prompt.md](./prompt.md) §5.3 · [03-functional-requirements.md](./03-functional-requirements.md) §12.

#### NFR-15 — Projection-friendly lecturer QR view

Lecturer QR display shall remain legible in classroom projection settings with clear refresh indication and open/closed state feedback.  
Trace: [03-functional-requirements.md](./03-functional-requirements.md) (`FR-14`) · [02-business-workflow.md](./02-business-workflow.md) §3.

### 2.6 Operability and observability

#### NFR-16 — Operational telemetry

The platform shall expose metrics and logs for check-in throughput, failure reason distribution, QR rotation health, and session open/close events, enabling issue triage during class-time peaks.  
Trace: [06-domain-model.md](./06-domain-model.md) §8, §9.

#### NFR-17 — Recovery and supportability

The operational model shall include incident response playbooks for check-in degradation (network instability, token service errors, GPS anomalies) and documented manual fallback procedures for lecturers.  
Trace: [02-business-workflow.md](./02-business-workflow.md) §6 · [04-business-rules.md](./04-business-rules.md) (`BR-14` to `BR-16`).

---

## 3. Constraints and assumptions

### 3.1 Constraints

| ID | Constraint | Impact on NFRs |
| --- | --- | --- |
| C-01 | Mobile-web platform only | Limits anti-spoofing and some device signals; reinforces `NFR-11` and risk controls |
| C-02 | Student device variance | Requires resilient UX and fallback; affects `NFR-01`, `NFR-14` |
| C-03 | Campus network variability | Requires retries, graceful error messaging, and manual fallback readiness |
| C-04 | Sensitive attendance/location data | Requires strict RBAC, audit, retention, and minimization controls |

### 3.2 Assumptions

| ID | Assumption | Validation approach |
| --- | --- | --- |
| A-01 | Most students have smartphone + camera + browser support | Pilot by faculty before broad rollout |
| A-02 | Enrollment files are available on schedule | Import validation and reconciliation reports |
| A-03 | Lecturers will execute open/close flow consistently | Training and usage analytics after launch |
| A-04 | GPS radius can be calibrated per room/campus | Field testing before strict enforcement |

---

## 4. Risk register (MVP)

### 4.1 Risk matrix

| Risk ID | Risk | Likelihood | Impact | Mitigation | Residual risk |
| --- | --- | --- | --- | --- | --- |
| RSK-01 | Peak concurrency at class start causes latency spikes | High | High | Capacity tests, autoscaling, idempotent APIs, rate-aware monitoring (`NFR-01`, `NFR-04`) | Medium |
| RSK-02 | Network instability blocks valid check-ins | Medium | High | Retry UX, clear failure reasons, manual fallback path (`BR-14`) | Medium |
| RSK-03 | GPS false negatives in dense buildings | Medium | High | Configurable radius, low-accuracy handling (`BR-10`), manual verification | Medium |
| RSK-04 | GPS spoofing or proxy behavior | High | High | Multi-layer controls: login + QR TTL + enrollment + one-success rule + audit + review; avoid absolute claims | Medium/High |
| RSK-05 | Unauthorized data export or overbroad access | Medium | Very High | Strict RBAC, scoped queries, export audit (`BR-18`, `BR-19`, `NFR-09`) | Medium |
| RSK-06 | Enrollment sync errors cause wrongful denial | Medium | High | Import validation, reconciliation dashboard, admin correction flow | Medium |
| RSK-07 | Lecturer errors during manual corrections | Medium | Medium | Confirmation UX, reason-required edits, immutable audit trail | Low/Medium |
| RSK-08 | Privacy incident from over-retention of GPS data | Low/Medium | Very High | Data minimization and retention policy enforcement (`NFR-11`, `NFR-12`) | Medium |
| RSK-09 | Token service/clock skew issues invalidate active QR unexpectedly | Low/Medium | High | Time sync controls, tolerant validation bounds, token observability | Low/Medium |

### 4.2 Top risk controls for launch gate

Before production rollout, Attendly should pass these controls:

1. Peak load rehearsal on representative concurrent sessions.
2. End-to-end audit completeness verification for check-in failures, edits, and exports.
3. GPS calibration test in representative classrooms.
4. RBAC penetration tests for report/export boundaries.
5. Lecturer manual fallback drill with dispute-resolution walkthrough.

---

## 5. Non-functional traceability

| NFR ID | Primary FR/BR trace | Acceptance linkage |
| --- | --- | --- |
| NFR-01, NFR-02, NFR-03, NFR-04 | `FR-16`, `FR-23`, `FR-22`; `BR-01` to `BR-13` | `AC-19`, `AC-20`, `AC-21` in [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md) |
| NFR-05, NFR-06, NFR-07 | `FR-07`, `FR-08`, `FR-18`; `BR-07`, `BR-21` | `AC-03`, `AC-05`, `AC-22` |
| NFR-08, NFR-09, NFR-10 | `FR-27`, `FR-29`, `FR-30`, `FR-32`; `BR-18`, `BR-19`, `BR-22` | `AC-13`, `AC-16`, `AC-17`, `AC-23` |
| NFR-11, NFR-12, NFR-13 | `FR-34`, `FR-35`, `FR-22`; `BR-08` to `BR-10`, `BR-23` | `AC-08`, `AC-09`, `AC-18`, `AC-24` |
| NFR-14, NFR-15, NFR-16, NFR-17 | `FR-14`, `FR-19`, `FR-20`; `BR-14` to `BR-16` | `AC-11`, `AC-12`, `AC-25` |

---

## 6. MVP quality baseline

### 6.1 Launch baseline

MVP launch should satisfy:

- All `NFR-01` to `NFR-13` at minimum threshold.
- `NFR-14` and `NFR-15` on supported mobile/browser matrix.
- Operational readiness for `NFR-16` and `NFR-17` with defined support ownership.

### 6.2 Quality exclusions (MVP)

MVP does not require:

- Absolute spoof-proof location assurance.
- Native-app-only anti-fraud signals.
- Full multi-campus failover architecture.

These remain outside launch quality scope and are handled in future phases.

---

## 7. Future consideration

Potential post-MVP quality enhancements:

- Multi-factor authentication and device binding for higher assurance.
- Proactive anomaly scoring across sessions and sections.
- Advanced data-loss prevention controls on exports.
- Extended disaster recovery objectives for multi-region operation.
- Automated privacy policy enforcement and deletion workflows per data category.

Roadmap and phase acceptance detail: [08-acceptance-mvp-future.md](./08-acceptance-mvp-future.md).
