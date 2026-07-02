# Attendly — Validation Rules

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [05-api-design.md](./05-api-design.md) · [06-main-workflows.md](./06-main-workflows.md) · [07-state-machines.md](./07-state-machines.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md)

## 1. Purpose and validation scope

This document defines server-side validation rules for Attendly MVP, including request shape validation, business-rule validation, permission validation, and data-integrity validation.

### 1.1 Validation objectives

| ID | Objective | Trace |
| --- | --- | --- |
| VR-01 | Reject invalid or ambiguous requests early with structured errors | FR-22, BR-23 |
| VR-02 | Enforce consistent check-in decision order | BR-05 to BR-12 |
| VR-03 | Prevent cross-scope and unauthorized data operations | BR-18, BR-19 |
| VR-04 | Keep attendance ledger consistent under retries/concurrency | BR-07, NFR-07 |

## 2. Validation layers

### 2.1 Layer model

| Layer | Scope | Example checks |
| --- | --- | --- |
| L1 Payload schema | Field format and type | UUID format, enum values, required fields |
| L2 Authentication | Actor identity | valid access token, active user |
| L3 Authorization | Role and scope | assigned section, faculty scope, export permissions |
| L4 Domain rules | Business state checks | session open, token TTL, enrollment, duplicate |
| L5 Persistence integrity | DB constraints and idempotency | unique attendance record key, foreign keys |

### 2.2 Required order for check-in validation

1. `Unauthenticated` check (BR-05)
2. Session state check (`SessionNotOpen`/`SessionClosed`) (BR-01, BR-02)
3. Token validity and expiry (`ExpiredQr`/invalid) (BR-03, BR-04)
4. Enrollment check (`NotEnrolled`) (BR-06)
5. Duplicate success check (`DuplicateCheckIn`) (BR-07)
6. GPS policy checks (`GpsRequired`, `GpsDisabled`, `OutOfRadius`, `LowAccuracy`) (BR-08 to BR-10)
7. Status assignment (`Present`/`Late`) and write path (BR-11, BR-12, BR-23)

## 3. Endpoint validation matrix

### 3.1 Check-in endpoint (`POST /v1/check-ins`)

| Rule ID | Rule | Failure code | Trace |
| --- | --- | --- | --- |
| VR-CI-01 | `qrToken` is required and non-empty | `InvalidPayload` | FR-16 |
| VR-CI-02 | actor role must include `Student` | `Forbidden` | FR-15 |
| VR-CI-03 | class session resolved from token must exist | `SessionNotFound` | FR-13 |
| VR-CI-04 | session state must be `Open` | `SessionNotOpen`/`SessionClosed` | BR-01, BR-02 |
| VR-CI-05 | token must be valid and not expired by server time | `ExpiredQr`/`InvalidQr` | BR-03, BR-04 |
| VR-CI-06 | student must have active enrollment in section | `NotEnrolled` | BR-06 |
| VR-CI-07 | no prior successful attendance for (`student`,`session`) | `DuplicateCheckIn` | BR-07 |
| VR-CI-08 | if GPS required, location payload must satisfy policy | GPS-related codes | BR-08 to BR-10 |
| VR-CI-09 | persist one `CheckInAttempt` for every terminal outcome | n/a | FR-22, BR-23 |

### 3.2 Session open/close endpoints

| Rule ID | Rule | Failure code | Trace |
| --- | --- | --- | --- |
| VR-SS-01 | actor must be assigned lecturer or authorized admin | `OutOfScope` | FR-07, BR-19 |
| VR-SS-02 | open is allowed only from `Scheduled` | `InvalidSessionTransition` | BR-01 |
| VR-SS-03 | close is allowed only from `Open` | `InvalidSessionTransition` | BR-02 |
| VR-SS-04 | close finalization must be idempotent | n/a | FR-09, NFR-07 |

### 3.3 Manual correction endpoint

| Rule ID | Rule | Failure code | Trace |
| --- | --- | --- | --- |
| VR-MC-01 | actor must have correction permission for target scope | `OutOfScope` | FR-20, FR-21 |
| VR-MC-02 | `status` must be allowed attendance enum value | `InvalidPayload` | FR-20 |
| VR-MC-03 | lecturer edit window must be valid, or admin override path applies | `EditWindowExpired` | BR-15, BR-16 |
| VR-MC-04 | reason is required when policy requires it | `ReasonRequired` | BR-14, BR-16 |
| VR-MC-05 | every accepted mutation writes audit record | n/a | FR-29, BR-22 |

### 3.4 Report/export endpoints

| Rule ID | Rule | Failure code | Trace |
| --- | --- | --- | --- |
| VR-RP-01 | query filters must be allow-listed and typed | `InvalidFilter` | FR-28 |
| VR-RP-02 | filters must be constrained to actor scope before execution | `OutOfScope` | BR-18, BR-19 |
| VR-RP-03 | export format must be supported (`csv`) | `UnsupportedFormat` | FR-27 |
| VR-RP-04 | successful export emits audit event | n/a | FR-30, BR-22 |

## 4. Field-level validation rules

### 4.1 Common field constraints

| Field | Constraint |
| --- | --- |
| UUID identifiers | RFC4122 format only |
| Datetime fields | ISO-8601 parsable |
| Pagination | `page >= 1`, `1 <= pageSize <= 100` |
| Sort parameters | server allow-list only |
| Enum fields | reject unknown value |

### 4.2 GPS payload constraints (policy enabled sessions)

| Field | Constraint | Failure code |
| --- | --- | --- |
| `gps.latitude` | numeric in [-90, 90] | `InvalidGpsPayload` |
| `gps.longitude` | numeric in [-180, 180] | `InvalidGpsPayload` |
| `gps.accuracyMeters` | numeric >= 0 | `InvalidGpsPayload` |
| Derived distance | compare to effective radius | `OutOfRadius` |
| Accuracy threshold | compare to policy threshold | `LowAccuracy` |

## 5. Data integrity rules

### 5.1 Persistence invariants

| ID | Invariant | Enforcement |
| --- | --- | --- |
| DI-V-01 | One attendance record per (`classSessionId`,`studentUserId`) | unique DB key + conflict handling |
| DI-V-02 | One check-in attempt outcome per request | transactional write path |
| DI-V-03 | Token belongs to one session and cannot validate across sessions | token/session binding |
| DI-V-04 | Closed sessions cannot accept success transitions | session-state guard |

### 5.2 Idempotency validation

| Command | Keying guidance | Behavior on replay |
| --- | --- | --- |
| `POST /v1/check-ins` | `Idempotency-Key` + actor + token | return prior result or deterministic duplicate conflict |
| `POST /open`, `POST /close` | `Idempotency-Key` + session + actor | return current state summary |
| `PATCH attendance` | `Idempotency-Key` + target attendance row | return prior applied mutation |

## 6. Validation error contract

### 6.1 Required error payload fields

- `error.code` (stable machine code)
- `error.message` (localized text)
- `error.details` (context, optional)
- `meta.requestId`
- `meta.timestamp`

### 6.2 Error code catalog (minimum)

| Group | Codes |
| --- | --- |
| Authentication | `Unauthenticated` |
| Authorization | `Forbidden`, `OutOfScope` |
| Session and token | `SessionNotOpen`, `SessionClosed`, `ExpiredQr`, `InvalidQr`, `InvalidSessionTransition` |
| Eligibility and duplicate | `NotEnrolled`, `DuplicateCheckIn` |
| GPS | `GpsRequired`, `GpsDisabled`, `OutOfRadius`, `LowAccuracy`, `InvalidGpsPayload` |
| Validation | `InvalidPayload`, `InvalidFilter`, `UnsupportedFormat` |

## 7. Test and acceptance mapping

| Validation area | Acceptance criteria |
| --- | --- |
| Check-in rule ordering and outcomes | AC-04, AC-06, AC-07, AC-08, AC-09, AC-10, AC-11 |
| Session transition guards | AC-01, AC-05, AC-12 |
| Manual correction authorization/time window | AC-13, AC-14 |
| Report/export scope validation | AC-15, AC-16, AC-17 |
| Failed attempt reason-code coverage | AC-18 |

## 8. Requirement traceability

| Validation domain | FR IDs | BR IDs | NFR IDs |
| --- | --- | --- | --- |
| Check-in schema and business validation | FR-15, FR-16, FR-17, FR-18, FR-22, FR-23, FR-34, FR-35 | BR-03, BR-04, BR-05, BR-06, BR-07, BR-08, BR-09, BR-10, BR-11, BR-12, BR-23 | NFR-01, NFR-03, NFR-07, NFR-13 |
| Session open/close validations | FR-07, FR-08, FR-09 | BR-01, BR-02, BR-13, BR-21 | NFR-06, NFR-07 |
| Manual correction validations | FR-20, FR-21, FR-29 | BR-14, BR-15, BR-16, BR-22 | NFR-09, NFR-10, NFR-13 |
| Report/export validations | FR-27, FR-28, FR-30, FR-32 | BR-18, BR-19, BR-22 | NFR-09, NFR-10 |

## 9. Future consideration

- Adaptive validation throttling based on section-level traffic spikes.
- Additional suspicious-attempt classifiers beyond rule-based checks.
- Policy explainability endpoint to return which policy level supplied each validation rule.

## 10. MVP boundary note

- Validation rules in this document are restricted to MVP and MVP-Should scope from [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md).
- Features explicitly out of scope (for example biometric/facial checks and native-only anti-fraud signals) are excluded from runtime validation decisions.

## 11. Implementation checklist

Use this checklist when implementing or reviewing validation middleware and handlers:

| Checkpoint | Expected outcome |
| --- | --- |
| Rule ordering in check-in path matches §2.2 exactly | deterministic and testable failure outcomes |
| Every terminal check-in outcome writes exactly one attempt row | complete attempt traceability (`FR-22`) |
| Scope filtering runs before report/export queries | no cross-scope leakage (`BR-19`) |
| Mutation endpoints enforce idempotency keys | retry-safe behavior under unstable networks |
| Validation error payloads include stable `error.code` | frontend can render localized, predictable UX |
