# Attendly — Testing Plan

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [05-api-design.md](./05-api-design.md) · [06-main-workflows.md](./06-main-workflows.md) · [07-state-machines.md](./07-state-machines.md) · [08-validation-rules.md](./08-validation-rules.md) · [09-error-handling.md](./09-error-handling.md) · [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md)

## 1. Purpose

This document defines the MVP testing strategy, coverage targets, and release test gates for Attendly.

## 2. Test strategy overview

### 2.1 Testing layers

| Layer | Scope | Goal |
| --- | --- | --- |
| Unit tests | pure functions/services | verify rule logic and edge cases quickly |
| Integration tests | API + DB + dependencies | validate transactional behavior and persistence invariants |
| End-to-end tests | browser + API runtime | validate real user workflows |
| Non-functional tests | load/security/reliability | validate NFR and operational readiness |

### 2.2 Scope priority

1. Check-in correctness and idempotency
2. Session lifecycle consistency
3. Role/scope authorization
4. Audit completeness
5. Export integrity

## 3. Requirement-based coverage plan

### 3.1 Functional and business rule mapping

| Coverage block | Target FR/BR/AC |
| --- | --- |
| Session open/close | FR-07, FR-08, BR-01, BR-02, AC-01, AC-05 |
| QR token behavior | FR-11, FR-12, BR-03, BR-04, AC-02, AC-03, AC-04 |
| Check-in eligibility and duplicate | FR-17, FR-18, BR-06, BR-07, AC-07, AC-08 |
| GPS validation | FR-34, FR-35, BR-08/09/10, AC-09, AC-10 |
| Attendance status assignment | FR-23, BR-11, BR-12, AC-11 |
| Close-time absent finalization | FR-09, BR-13, AC-12 |
| Manual correction governance | FR-20, FR-21, BR-14/15/16, AC-13, AC-14 |
| Reporting/export and scope | FR-27, FR-28, BR-18, BR-19, AC-15, AC-16, AC-17 |
| Attempt/audit coverage | FR-22, FR-29, FR-30, BR-22, BR-23, AC-18, AC-19 |

## 4. Unit testing plan

### 4.1 Core unit suites

| Suite | Example test cases |
| --- | --- |
| Policy resolution | section-over-course precedence, fallback defaults |
| Attendance window logic | boundary times for `Present` vs `Late` |
| GPS validators | radius pass/fail, low accuracy classification |
| Error mapper | domain error -> stable API error code |
| Scope guards | lecturer section boundary and admin override rules |

### 4.2 Unit quality target

- Critical domain modules: >= 85% statement coverage.
- Non-critical utility modules: >= 70% statement coverage.

Coverage is guidance; release decisions prioritize risk-based scenarios and acceptance tests.

## 5. Integration testing plan

### 5.1 API + DB integration suites

| Suite | Focus |
| --- | --- |
| check-in transaction | one attempt outcome per request, one success record per student/session |
| session transition | legal and illegal state transitions |
| manual correction | edit window enforcement and audit write |
| report/export | scope filtering and CSV schema consistency |
| audit persistence | mutation and export audit completeness |

### 5.2 Data integrity checks

- Unique key enforcement for attendance record.
- FK enforcement across session/token/attempt entities.
- Idempotent replay handling for mutation endpoints.

## 6. End-to-end testing plan

### 6.1 MVP user journeys

| Journey ID | Scenario | Expected result |
| --- | --- | --- |
| E2E-01 | Lecturer opens session and displays rotating QR | session becomes `Open`, QR refreshes |
| E2E-02 | Student successful check-in within present window | `Present` recorded |
| E2E-03 | Student duplicate submission | `DuplicateCheckIn`, no extra success row |
| E2E-04 | Student expired QR attempt then rescan | first fail `ExpiredQr`, second can succeed |
| E2E-05 | GPS-required flow with denied permission | `GpsDisabled`, manual fallback route visible |
| E2E-06 | Lecturer manual correction in allowed window | status updated + audit |
| E2E-07 | Session close finalizes unresolved as `Absent` | absent rows generated |
| E2E-08 | Lecturer export limited to assigned sections | no cross-scope rows |

### 6.2 Browser matrix

- iOS Safari (mobile student flow)
- Android Chrome (mobile student flow)
- Chromium desktop (lecturer/admin flow)

## 7. Non-functional testing plan

### 7.1 Performance tests

| Test | Target |
| --- | --- |
| check-in latency under normal load | median < 30s (`AC-20`) |
| class-start burst | majority complete < 5m (`AC-21`) |
| valid request success rate | >= 99% (`AC-22`) |

### 7.2 Reliability tests

- Retry storms on `POST /v1/check-ins` with same idempotency key.
- Overlap of session close and in-flight submissions.
- Token expiry boundary tests around TTL edges.

### 7.3 Security and authorization tests

- Role-based route access matrix for all six roles.
- Scope isolation tests for report/export.
- Negative tests for privilege escalation attempts.

### 7.4 Privacy checks

- GPS fields present only when policy requires.
- No continuous location tracking behavior.
- Retention jobs or scripts enforce data minimization policy.

## 8. Test data management

### 8.1 Required fixture sets

| Fixture set | Purpose |
| --- | --- |
| `base-academic` | term/course/section/room baseline |
| `role-matrix` | users across all roles and scopes |
| `attendance-open-session` | active open session with enrollments |
| `gps-required-session` | location validation scenarios |
| `dispute-trail` | attempts + corrections + exports for audit checks |

### 8.2 Test data rules

- Use deterministic IDs where feasible in integration tests.
- Keep PII-like fields synthetic.
- Reset DB state between suites to avoid cross-test contamination.

## 9. CI test gates

### 9.1 Pull request gates (minimum)

1. Lint and type checks pass.
2. Unit tests pass.
3. Critical integration tests pass (check-in, session transition, export scope, audit writes).
4. Changed API contracts validated against schema snapshots.

### 9.2 Pre-release gates

1. Full integration + E2E suite pass.
2. NFR performance smoke targets pass.
3. Security authorization regression suite pass.
4. Acceptance criteria trace set (`AC-01` to `AC-25`) has no blocker failures.

### 9.3 Flaky-test control and test isolation policy

To keep release confidence stable, CI and local pipelines must explicitly manage flaky behavior and enforce test isolation:

| Policy | Requirement |
| --- | --- |
| flaky test detection | Any intermittently failing test is tagged and triaged within the same sprint; repeat offenders block release promotion until stabilized |
| flake budget | Release branches target zero unresolved high-impact flake in check-in, session lifecycle, export, and audit suites |
| test isolation | Every test must run with isolated data/setup so execution order does not change outcomes |
| environment reset | Integration/E2E suites reset database and cache state between scenarios to preserve test isolation guarantees |
| deterministic fixtures | Shared fixtures use deterministic IDs/timestamps where feasible to reduce flake from timing variance |

## 10. Defect triage policy

### 10.1 Severity model

| Severity | Definition |
| --- | --- |
| Sev-1 | blocks class check-in operations or corrupts attendance integrity |
| Sev-2 | major workflow issue with workaround |
| Sev-3 | minor functional issue or non-critical UX defect |
| Sev-4 | cosmetic/documentation defect |

### 10.2 Release blockers

Release is blocked by:
- any open Sev-1
- unresolved Sev-2 in check-in/session/export/audit paths
- failing AC-linked critical scenarios

## 11. NFR verification matrix

| NFR ID | Verification method | Minimum evidence |
| --- | --- | --- |
| NFR-01 | timed E2E + API telemetry | median check-in < 30s in representative load run |
| NFR-02 | class-start burst test | majority completed check-ins < 5 minutes |
| NFR-03 | load test plus rule-pass subset | valid request success >= 99% |
| NFR-06 | state-transition integration tests | no illegal transitions committed |
| NFR-07 | concurrency + idempotency tests | one success per student/session under retries |
| NFR-09 | authorization regression suite | no cross-scope data leakage |
| NFR-10 | mutation audit completeness checks | 100% mutation audit rows present |
| NFR-11, NFR-12 | GPS privacy tests | event-only collection and bounded retention |
| NFR-13 | failure-path coverage tests | 100% failed attempts with reason code |
| NFR-16, NFR-17 | operational drill and runbook review | alerting and manual fallback rehearsed |

## 12. Requirement traceability

| Test domain | FR IDs | BR IDs | AC IDs |
| --- | --- | --- | --- |
| Session lifecycle and QR | FR-07, FR-08, FR-09, FR-11, FR-12, FR-13, FR-14 | BR-01, BR-02, BR-03, BR-04, BR-13, BR-21 | AC-01, AC-02, AC-03, AC-04, AC-05, AC-12 |
| Student check-in validation | FR-15, FR-16, FR-17, FR-18, FR-22, FR-23 | BR-05, BR-06, BR-07, BR-11, BR-12, BR-23 | AC-06, AC-07, AC-08, AC-11, AC-18 |
| GPS policy validation | FR-34, FR-35 | BR-08, BR-09, BR-10 | AC-09, AC-10 |
| Manual correction and governance | FR-20, FR-21, FR-29 | BR-14, BR-15, BR-16, BR-22 | AC-13, AC-14, AC-19, AC-25 |
| Reporting/export and permissions | FR-27, FR-28, FR-30, FR-32 | BR-18, BR-19, BR-22 | AC-15, AC-16, AC-17 |

## 13. Future consideration

- Contract testing between frontend and backend schema.
- Chaos testing for dependency outages during class-start peaks.
- Property-based testing for policy precedence and time-window edge cases.

## 14. MVP boundary note

- MVP release blocking coverage is `AC-01` through `AC-25` only, aligned with [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md).
- Future-phase tests should be tracked separately and must not delay MVP sign-off unless they expose regression in MVP requirements.

## 15. Minimum regression suite

Run this suite on every merge to protect the attendance critical path:

| Suite ID | Scope |
| --- | --- |
| REG-01 | session open/close transition guards |
| REG-02 | QR TTL behavior + expired-token rejection |
| REG-03 | one-success-per-student duplicate prevention |
| REG-04 | manual correction with edit-window and scope enforcement |
| REG-05 | report/export scope filtering and audit completeness |
