# Attendly — Error Handling

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [05-api-design.md](./05-api-design.md) · [06-main-workflows.md](./06-main-workflows.md) · [08-validation-rules.md](./08-validation-rules.md) · [11-testing-plan.md](./11-testing-plan.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../brds/07-non-functional-risk.md](../brds/07-non-functional-risk.md)

## 1. Purpose and principles

This document defines runtime error handling policy for Attendly services and APIs.

### 1.1 Error handling principles

| ID | Principle | Rationale |
| --- | --- | --- |
| EH-01 | Fail fast on invalid input | Reduce ambiguous behavior and protect data integrity |
| EH-02 | Return deterministic error codes | Keep client UX and retries predictable |
| EH-03 | Preserve auditability on critical failures | Support dispute and compliance requirements |
| EH-04 | Do not leak sensitive internals | Protect security posture |
| EH-05 | Prefer graceful degradation over silent failure | Keep classroom operations resilient |

## 2. Error taxonomy

### 2.1 Categories

| Category | Description | Typical HTTP |
| --- | --- | --- |
| Validation error | Payload/format/constraint failure | 400 |
| Authentication error | Missing or invalid identity | 401 |
| Authorization error | Role or scope denied | 403 |
| Not found | Resource absent | 404 |
| Business rule conflict | Valid payload, invalid domain state | 409/422 |
| Rate-limit error | Throughput controls triggered | 429 |
| Dependency error | External service unavailable/timeout | 503 |
| Internal error | Unexpected application fault | 500 |

### 2.2 Canonical business error codes

| Code | Primary workflow impact |
| --- | --- |
| `SessionNotOpen` | student cannot check in until lecturer opens |
| `SessionClosed` | self check-in blocked after close; manual fallback path |
| `ExpiredQr` | student must re-scan current QR |
| `NotEnrolled` | student denied based on section roster |
| `DuplicateCheckIn` | repeat check-in rejected, original success preserved |
| `GpsRequired` / `GpsDisabled` | location requirement unresolved |
| `OutOfRadius` / `LowAccuracy` | GPS check failed or uncertain |
| `OutOfScope` | actor attempted action outside authorized scope |
| `EditWindowExpired` | lecturer correction requires admin path |

## 3. API response contract for errors

### 3.1 Required response shape

Every error response must include:
- `meta.requestId`
- `meta.timestamp`
- `error.code`
- `error.message`
- `error.details` (optional contextual values)

### 3.2 Message policy

| Rule | Requirement |
| --- | --- |
| Student-facing messages | concise Vietnamese guidance text |
| Staff-facing messages | actionable and scoped; no stack traces |
| Logs-only details | stack traces and low-level diagnostics remain server-side only |

## 4. Workflow-specific handling

### 4.1 Check-in flow errors

| Failure point | Error code | Client behavior | Server behavior |
| --- | --- | --- | --- |
| unauthenticated | `Unauthenticated` | redirect login | reject with 401 |
| session not open | `SessionNotOpen` | show wait guidance | persist failed attempt when identity/session context is resolvable |
| token expired | `ExpiredQr` | prompt re-scan | persist failed attempt |
| not enrolled | `NotEnrolled` | contact admin guidance | persist failed attempt |
| duplicate success | `DuplicateCheckIn` | show existing status | persist failed attempt |
| GPS failure | GPS codes | retry or manual fallback guidance | persist failed attempt with validation metadata |

### 4.2 Session open/close errors

| Scenario | Error code | Handling |
| --- | --- | --- |
| lecturer not assigned | `OutOfScope` | reject; no state mutation |
| invalid state transition | `InvalidSessionTransition` | return current state summary where possible |
| close overlap/retry | none or conflict code | idempotent close response; no double finalization |

### 4.3 Manual correction errors

| Scenario | Error code | Handling |
| --- | --- | --- |
| out-of-scope actor | `OutOfScope` | reject without data leakage |
| expired edit window | `EditWindowExpired` | reject or route to admin workflow |
| missing required reason | `ReasonRequired` | reject with 400 |

### 4.4 Report/export errors

| Scenario | Error code | Handling |
| --- | --- | --- |
| out-of-scope filter | `OutOfScope` | reject before query execution |
| unsupported export format | `UnsupportedFormat` | reject with allowed format list |
| export job backend unavailable | `ExportServiceUnavailable` | return retryable 503 and log incident |

## 5. Retry and idempotency policy

### 5.1 Retry classes

| Error class | Retry by client |
| --- | --- |
| 4xx validation/authorization/business | No automatic retry |
| 429 rate limit | Retry with backoff after `Retry-After` |
| 503 dependency unavailable | Retry with bounded exponential backoff |
| 500 internal error | Retry only for idempotent command with same idempotency key |

### 5.2 Idempotency requirements

- All mutation endpoints require `Idempotency-Key`.
- Retries must not duplicate attendance success or correction writes.
- Replay with same key should return prior committed result where possible.

Trace: FR-18, FR-20, FR-21, NFR-07.

## 6. Logging, audit, and observability

### 6.1 Structured error logging fields

| Field | Required |
| --- | --- |
| `requestId` | yes |
| `correlationId` | yes for command paths |
| `actorUserId` | when authenticated |
| `endpoint` and `method` | yes |
| `errorCode` | yes |
| `httpStatus` | yes |
| `scopeContext` | for authorization failures |

### 6.2 Audit requirements on error paths

| Path | Audit expectation |
| --- | --- |
| failed check-in attempts | persisted with reason code (100%) |
| denied privileged report/export attempts | log by policy for security visibility |
| failed manual correction | error logged; no mutation audit entry unless write happened |

## 7. Operational incident handling

### 7.1 Severity levels

| Level | Definition | Example |
| --- | --- | --- |
| Sev-1 | broad check-in outage during class time | check-in API unavailable |
| Sev-2 | major degradation with fallback available | token rotation delayed, high `ExpiredQr` spikes |
| Sev-3 | localized non-critical fault | export queue delay |

### 7.2 Incident playbook (minimum)

1. Detect via metrics/log alert (`NFR-16` alignment)
2. Triage scope: section/faculty/system-wide
3. Apply mitigation (scaling, restart, dependency failover, temporary policy relaxation)
4. Communicate operator guidance (including manual fallback where needed)
5. Post-incident review with root cause and prevention action

## 8. Traceability

| Error-handling area | FR/BR/NFR/AC |
| --- | --- |
| Check-in deterministic failures | BR-03 to BR-12, FR-22, AC-04/06/07/08/09/10/11/18 |
| Session transition conflicts | FR-07, FR-08, BR-01, BR-02, AC-01, AC-05 |
| Manual correction governance | FR-20, FR-21, BR-14/15/16, AC-13, AC-14 |
| Export and scope denials | FR-27, FR-30, BR-18, BR-19, AC-15/16/17 |
| Observability and resilience | NFR-16, NFR-17, AC-25 |

## 9. Error code to rule mapping

| Error code | FR/BR anchors | Handling owner |
| --- | --- | --- |
| `SessionNotOpen`, `SessionClosed` | FR-07, FR-08, BR-01, BR-02 | Session Lifecycle |
| `ExpiredQr`, `InvalidQr` | FR-11, FR-13, BR-03, BR-04 | Check-in and QR Orchestrator |
| `NotEnrolled` | FR-17, BR-06 | Academic Structure + Check-in Orchestrator |
| `DuplicateCheckIn` | FR-18, BR-07 | Attendance Ledger |
| `GpsRequired`, `GpsDisabled`, `OutOfRadius`, `LowAccuracy` | FR-34, FR-35, BR-08, BR-09, BR-10 | Policy Engine + Check-in Orchestrator |
| `OutOfScope`, `Forbidden` | FR-27, FR-28, FR-32, BR-18, BR-19 | Identity and Access |
| `EditWindowExpired`, `ReasonRequired` | FR-20, FR-21, BR-14, BR-15, BR-16 | Attendance Ledger |

## 10. Future consideration

- Centralized error catalog service shared by API and frontend localization.
- Automated root-cause clustering for repeated error bursts.
- Self-serve diagnostics for campus IT operators.

## 11. MVP boundary note

- Error handling behavior here intentionally avoids non-MVP claims such as absolute anti-spoof detection.
- When GPS validation is enabled, outcomes remain policy-based (`OutOfRadius`, `LowAccuracy`, `Suspicious`) and keep the manual fallback path available per BR-14 and AC-25.

## 12. Operational checklist

Before each release, verify:

| Checkpoint | Expected result |
| --- | --- |
| Error code catalog in API implementation matches this document | no drift between backend and frontend handling |
| Failed check-in attempts retain structured reason code coverage | meets `AC-18` and `NFR-13` |
| Export and correction failures are visible in logs with request correlation | production triage remains fast |
| Sev-1/Sev-2 runbooks are tested by tabletop drill | team can execute fallback during class-time incidents |
