# Attendly — Technical Domain Model

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-system-overview.md](./00-system-overview.md) · [01-roles-permissions.md](./01-roles-permissions.md) · [02-module-breakdown.md](./02-module-breakdown.md) · [../brds/06-domain-model.md](../brds/06-domain-model.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md)

## 1. Purpose

This document defines the technical domain model for Attendly MVP: aggregates, entities, value objects, lifecycle invariants, and event boundaries used by application services and persistence.

## 2. Domain Scope and Bounded Contexts

### 2.1 Core bounded contexts

| Context | Responsibilities | Key requirement trace |
| --- | --- | --- |
| Identity & Access | Authentication, role/scope authorization, actor attribution | FR-15, FR-31, FR-32, BR-19 |
| Academic Structure | Terms, courses, sections, rooms, enrollment | FR-01 to FR-06, FR-17 |
| Session Operations | Session state transitions and QR activation lifecycle | FR-07, FR-08, FR-11, BR-01, BR-02 |
| Attendance Processing | Check-in decisions, attempt recording, final attendance outcomes | FR-18, FR-22, FR-23, BR-07, BR-23 |
| Policy & Compliance | Effective policy resolution, edit windows, audit logging | FR-24 to FR-30, BR-20, BR-22 |

### 2.2 Out of scope in this model (MVP)

- Biometrics/facial identity modeling.
- Device fingerprint trust model.
- Native-app telemetry entities.
- Continuous location tracking entities.

Future expansion is listed in §12.

## 3. Aggregate Design

### 3.1 Aggregate roots

| Aggregate root | In-aggregate members | Invariant focus |
| --- | --- | --- |
| `User` | role assignments, status flags | Actor identity and authorization scope |
| `ClassSection` | enrollments, policy override references | Enrollment eligibility and section ownership |
| `ClassSession` | QR tokens, attendance records, check-in attempts | Session lifecycle and one-success-per-student constraint |
| `AttendancePolicy` | scoped policy configuration | Effective policy precedence |
| `AuditLog` | immutable event entries | Compliance and forensic traceability |

### 3.2 Aggregate boundaries

- Cross-aggregate updates are event-driven where possible.
- `ClassSession` write path is the critical boundary for check-in correctness.
- `AuditLog` is append-only and external to business aggregates.

## 4. Entity Model

### 4.1 Identity entities

| Entity | Key fields | Notes |
| --- | --- | --- |
| `User` | `id`, `email`, `displayName`, `isActive` | Canonical authenticated actor |
| `UserRoleAssignment` | `id`, `userId`, `role`, `scopeType`, `scopeId` | Supports section/faculty/institution scoping |
| `StudentProfile` | `userId`, `studentCode`, `facultyId` | Optional one-to-one from `User` |
| `LecturerProfile` | `userId`, `staffCode`, `facultyId` | Optional one-to-one from `User` |

### 4.2 Academic structure entities

| Entity | Key fields | Notes |
| --- | --- | --- |
| `Faculty` | `id`, `code`, `name`, `isActive` | Department boundary for `DepartmentAdmin` |
| `Term` | `id`, `code`, `name`, `startDate`, `endDate`, `isActive` | Semester container |
| `Course` | `id`, `code`, `name`, `facultyId`, `isActive` | Subject catalog entity |
| `ClassSection` | `id`, `sectionCode`, `courseId`, `termId`, `lecturerUserId`, `defaultRoomId` | Primary roster and session scope |
| `Room` | `id`, `code`, `name`, `latitude`, `longitude`, `isActive` | GPS anchor when enabled |
| `Enrollment` | `id`, `classSectionId`, `studentUserId`, `status`, `enrolledAt`, `droppedAt` | Eligibility source for BR-06 |

### 4.3 Session and attendance entities

| Entity | Key fields | Notes |
| --- | --- | --- |
| `ClassSession` | `id`, `classSectionId`, `scheduledStartAt`, `scheduledEndAt`, `state`, `openedAt`, `closedAt` | Unit of attendance operation |
| `QRSessionToken` | `id`, `classSessionId`, `tokenHash`, `issuedAt`, `expiresAt`, `state` | Short-lived multi-use token (30s default) |
| `CheckInAttempt` | `id`, `classSessionId`, `studentUserId`, `qrTokenId`, `outcome`, `submittedAt` | Immutable attempt log |
| `AttendanceRecord` | `id`, `classSessionId`, `studentUserId`, `status`, `checkInMethod`, `checkInAt`, `lastModifiedAt` | Official per-student session outcome |

### 4.4 Policy and compliance entities

| Entity | Key fields | Notes |
| --- | --- | --- |
| `AttendancePolicy` | `id`, `scopeType`, `scopeId`, `presentWindowMinutes`, `lateWindowMinutes`, `gpsRequired`, `gpsRadiusMeters` | Scoped hierarchical policy |
| `PolicySnapshot` | `id`, `classSessionId`, `resolvedJson`, `resolvedAt` | Optional immutable runtime snapshot |
| `AuditLog` | `id`, `timestamp`, `actorUserId`, `actionType`, `targetType`, `targetId`, `oldValue`, `newValue`, `reason` | Required for BR-22, BR-23 |

## 5. Value Objects and Enums

### 5.1 Value objects

| Value object | Fields |
| --- | --- |
| `GeoPoint` | `latitude`, `longitude` |
| `GpsValidation` | `required`, `distanceMeters`, `accuracyMeters`, `result` |
| `AttendanceWindow` | `presentUntil`, `lateUntil`, `autoCloseAt` |
| `ScopeRef` | `scopeType`, `scopeId` |

### 5.2 Enums

| Enum | Values | Trace |
| --- | --- | --- |
| `SessionState` | `Scheduled`, `Open`, `Closed`, `Cancelled` | BR-01, BR-02 |
| `QrTokenState` | `Valid`, `Expired`, `Invalid` | BR-03, BR-04 |
| `AttendanceStatus` | `Pending`, `Present`, `Late`, `Absent`, `Excused`, `Manual Present` | BR-11 to BR-16 |
| `CheckInOutcome` | `Success`, `ExpiredQr`, `SessionNotOpen`, `SessionClosed`, `NotEnrolled`, `DuplicateCheckIn`, `GpsRequired`, `GpsDisabled`, `OutOfRadius`, `LowAccuracy`, `Unauthenticated`, `Suspicious` | FR-22, BR-23 |
| `CheckInMethod` | `QR`, `Manual`, `Admin Correction` | FR-20, FR-21, FR-23 |
| `EnrollmentStatus` | `Active`, `Dropped`, `Completed` | FR-04, BR-06 |
| `PolicyScopeType` | `Institution`, `Faculty`, `Course`, `ClassSection` | FR-24, BR-20 |

## 6. Relationship Model

### 6.1 Cardinality matrix

| From | To | Cardinality |
| --- | --- | --- |
| `Term` | `ClassSection` | 1 -> many |
| `Course` | `ClassSection` | 1 -> many |
| `ClassSection` | `Enrollment` | 1 -> many |
| `User(Student)` | `Enrollment` | 1 -> many |
| `ClassSection` | `ClassSession` | 1 -> many |
| `ClassSession` | `QRSessionToken` | 1 -> many |
| `ClassSession` | `CheckInAttempt` | 1 -> many |
| `ClassSession` | `AttendanceRecord` | 1 -> many |
| `User` | `AuditLog` | 1 -> many |
| `AttendancePolicy` | (`Institution` or scoped entity) | many -> one scope |

### 6.2 Logical ER summary

- `Enrollment` uniqueness: one row per (`classSectionId`, `studentUserId`).
- `AttendanceRecord` uniqueness: one row per (`classSessionId`, `studentUserId`).
- `QRSessionToken` belongs to exactly one session.
- `CheckInAttempt` may exist with null `qrTokenId` for malformed payloads.

## 7. Domain Invariants

| Invariant ID | Description | Enforced by |
| --- | --- | --- |
| DI-01 | Check-in accepted only when session state is `Open` | BR-01, BR-02 |
| DI-02 | QR token accepted only if `Valid` and not expired | BR-03, BR-04 |
| DI-03 | Student must have active enrollment to check in | BR-06 |
| DI-04 | One successful attendance record per student per session | BR-07 |
| DI-05 | Present/Late decided by effective policy window | BR-11, BR-12, BR-20 |
| DI-06 | Absent auto-assigned at session close for unresolved students | BR-13 |
| DI-07 | Lecturer edits limited by section scope and edit window | BR-14, BR-15 |
| DI-08 | Admin correction requires role scope and reason where configured | BR-16 |
| DI-09 | All attendance mutations and exports create audit entries | BR-18, BR-22 |
| DI-10 | Every check-in attempt stored with outcome code | BR-23 |

## 8. Domain Events

### 8.1 Core events

| Event | Producer | Primary consumers |
| --- | --- | --- |
| `SessionOpened` | Session service | QR rotation, realtime dashboard, audit |
| `SessionClosed` | Session service | Absent finalization, audit, reporting |
| `QrTokenIssued` | QR service | Lecturer display, telemetry |
| `CheckInAttemptRecorded` | Check-in service | Audit, analytics, fraud review |
| `AttendanceRecorded` | Check-in service | Realtime dashboard, reports |
| `AttendanceCorrected` | Attendance service | Audit, reports |
| `ExportCompleted` | Reporting service | Audit |

### 8.2 Event guarantees

- At-least-once delivery between modules is acceptable with idempotent consumers.
- `AttendanceRecorded` and `CheckInAttemptRecorded` must include correlation ID.
- `SessionClosed` consumers must be safe for repeated delivery.

## 9. State Transition Ownership

| Transition | Owner service | Trace |
| --- | --- | --- |
| `Scheduled` -> `Open` | Session service | FR-07 |
| `Open` -> `Closed` | Session service / policy scheduler | FR-08, BR-21 |
| `Pending` -> `Present` / `Late` | Check-in service | FR-23 |
| `Pending` -> `Absent` | Session close finalizer | FR-09, BR-13 |
| any -> manual/admin status | Attendance correction service | FR-20, FR-21 |
| `Valid` -> `Expired` | QR scheduler/time check | FR-11, BR-03 |

## 10. Traceability Mapping

### 10.1 Entity-to-requirement trace

| Entity | FR | BR | NFR / AC |
| --- | --- | --- | --- |
| `ClassSession` | FR-06, FR-07, FR-08 | BR-01, BR-02, BR-21 | AC-01, AC-05 |
| `QRSessionToken` | FR-11, FR-12, FR-13 | BR-03, BR-04 | AC-02, AC-04 |
| `CheckInAttempt` | FR-22 | BR-23 | NFR-13, AC-18 |
| `AttendanceRecord` | FR-18, FR-23, FR-20, FR-21 | BR-07, BR-11 to BR-16 | AC-08, AC-11 to AC-14 |
| `Enrollment` | FR-04, FR-17 | BR-06 | AC-07 |
| `AttendancePolicy` | FR-24, FR-25, FR-26 | BR-20 | AC-09, AC-10 |
| `AuditLog` | FR-29, FR-30 | BR-22 | AC-17, AC-19 |

### 10.2 Cross-links

- Permissions and role scope rules: [01-roles-permissions.md](./01-roles-permissions.md)
- Module ownership of domain objects: [02-module-breakdown.md](./02-module-breakdown.md)
- Physical table design and index strategy: [04-database-design.md](./04-database-design.md)

## 11. MVP Modeling Decisions

1. `User` is the principal identity key across all actor types.
2. Session QR token is modeled as multi-use within TTL, never as globally one-time.
3. `AttendanceRecord` is the single source of truth for final status.
4. Rejected attempts remain in `CheckInAttempt` and do not become roster states.
5. GPS raw coordinates are optional fields and governed by retention policy.

## 12. Future Consideration

- `DisputeCase` aggregate for formal appeals workflow.
- `TrustedDevice` entity for future device binding.
- `StudentChallengeToken` for per-student second-factor check-in hardening.
- `IntegrationSubscription` for outbound webhooks to academic systems.
- Multi-campus hierarchy (`Campus` above `Faculty`) when needed.

