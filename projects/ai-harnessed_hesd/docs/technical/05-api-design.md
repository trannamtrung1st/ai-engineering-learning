# Attendly — API Design

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-system-overview.md](./00-system-overview.md) · [01-roles-permissions.md](./01-roles-permissions.md) · [02-module-breakdown.md](./02-module-breakdown.md) · [03-domain-model.md](./03-domain-model.md) · [04-database-design.md](./04-database-design.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../brds/08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md)

## 1. Purpose and API scope

This document defines API contracts for Attendly MVP: endpoint boundaries, payload conventions, validation order, response semantics, idempotency strategy, and traceability to `FR-xx`, `BR-xx`, `AC-xx`, and `NFR-xx`.

### 1.1 API design goals

| Goal ID | Goal | Trace |
| --- | --- | --- |
| API-G01 | Deterministic check-in decisions under peak load | FR-22, BR-23, NFR-03 |
| API-G02 | Strict role- and scope-based access control | FR-27, BR-19, NFR-09 |
| API-G03 | Idempotent write behavior for retry-safe clients | BR-07, NFR-07 |
| API-G04 | Structured auditability for mutations and exports | FR-29, FR-30, BR-22 |
| API-G05 | Mobile-first, low-latency check-in payloads | FR-16, NFR-01 |

### 1.2 MVP API domains

| Domain | Primary endpoints |
| --- | --- |
| Authentication and actor context | `/v1/auth/*`, `/v1/me` |
| Academic structure | `/v1/terms`, `/v1/courses`, `/v1/class-sections`, `/v1/enrollments` |
| Session lifecycle | `/v1/class-sessions`, `/v1/class-sessions/{id}/open`, `/close` |
| QR and check-in | `/v1/class-sessions/{id}/qr/current`, `/v1/check-ins` |
| Attendance ledger | `/v1/class-sessions/{id}/attendance`, correction endpoints |
| Reporting and export | `/v1/reports/*`, `/v1/exports` |
| Audit | `/v1/audit-logs` |

## 2. API conventions

### 2.1 Transport and versioning

| Item | Convention |
| --- | --- |
| Protocol | HTTPS only in non-local environments |
| Base path | `/v1` |
| Media type | `application/json` |
| Charset | UTF-8 |
| Date-time | ISO-8601 UTC |
| Locale | `vi-VN` user-facing message keys; technical fields in English |

### 2.2 Request metadata

| Header | Required | Purpose |
| --- | --- | --- |
| `Authorization: Bearer <token>` | Yes (except login) | Authenticated actor |
| `X-Request-Id` | Should | Trace correlation across services |
| `Idempotency-Key` | Must on mutation endpoints | Retry-safe command processing |
| `Accept-Language` | Optional | Localized user message selection |

### 2.3 Response envelope

All non-stream responses use:

```json
{
  "data": {},
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:00Z"
  },
  "error": null
}
```

Error responses:

```json
{
  "data": null,
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:00Z"
  },
  "error": {
    "code": "SessionClosed",
    "message": "Buoi hoc da dong diem danh.",
    "details": {
      "classSessionId": "uuid"
    }
  }
}
```

### 2.4 Error classes

| HTTP | Error type | Example codes |
| --- | --- | --- |
| `400` | Validation errors | `InvalidPayload`, `MalformedQrToken` |
| `401` | Authentication failures | `Unauthenticated` |
| `403` | Authorization/scope failures | `Forbidden`, `OutOfScope` |
| `404` | Missing resources | `SessionNotFound` |
| `409` | Business conflict | `DuplicateCheckIn`, `InvalidSessionTransition` |
| `422` | Rule evaluation failures | `ExpiredQr`, `NotEnrolled`, `OutOfRadius` |
| `429` | Rate limiting | `TooManyRequests` |
| `500` | Server errors | `InternalError` |

### 2.5 Pagination, sorting, and filtering

List endpoints use consistent query parameters so UI listing pages and exports can share the same scope-aware filter model.

| Parameter | Type | Applies to | Behavior |
| --- | --- | --- | --- |
| `page` | integer | list/report endpoints | 1-based page number; default `1` |
| `pageSize` | integer | list/report endpoints | default `25`; maximum `100` for interactive lists |
| `sortBy` | string | list/report endpoints | allow-listed server field, never raw SQL |
| `sortOrder` | enum | list/report endpoints | `asc` or `desc` |
| `search` | string | class sections, reports, audit logs | normalized text search within authorized scope |
| `from`, `to` | ISO date/time | sessions, reports, audit logs | inclusive time range in UTC |

Paginated responses include:

```json
{
  "data": [],
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:00Z",
    "pagination": {
      "page": 1,
      "pageSize": 25,
      "totalItems": 120,
      "totalPages": 5
    }
  },
  "error": null
}
```

All list filters are applied after API authorization resolves role scope (`BR-18`, `BR-19`). The API must not expose cross-scope counts in pagination metadata.

## 3. Canonical API enums

### 3.1 Session and attendance enums

| Field | Allowed values | Trace |
| --- | --- | --- |
| `sessionState` | `Scheduled`, `Open`, `Closed`, `Cancelled` | BR-01, BR-02 |
| `qrTokenState` | `Valid`, `Expired`, `Invalid` | BR-03, BR-04 |
| `attendanceStatus` | `Pending`, `Present`, `Late`, `Absent`, `Excused`, `Manual Present` | BR-11 to BR-16 |
| `checkInMethod` | `QR`, `Manual`, `Admin Correction` | FR-20, FR-21, FR-23 |

### 3.2 Check-in outcome codes

| Outcome code | Meaning |
| --- | --- |
| `Success` | Check-in accepted |
| `ExpiredQr` | QR token expired |
| `SessionNotOpen` | Session not in `Open` state |
| `SessionClosed` | Session already closed |
| `NotEnrolled` | Student not enrolled in section |
| `DuplicateCheckIn` | Student already has successful record |
| `GpsRequired` | GPS required but not provided |
| `GpsDisabled` | Permission denied/unavailable |
| `OutOfRadius` | GPS outside allowed radius |
| `LowAccuracy` | GPS accuracy below threshold |
| `Unauthenticated` | Missing/invalid authentication |
| `Suspicious` | Flagged for review |

## 4. Endpoint catalog

### 4.1 Authentication and actor context

#### `POST /v1/auth/login`

- **Purpose:** issue access token for user login.
- **Trace:** FR-15, FR-36.

Request:

```json
{
  "email": "student@attendly.edu.vn",
  "password": "string"
}
```

Response (`200`):

```json
{
  "data": {
    "accessToken": "jwt",
    "expiresInSeconds": 3600,
    "roles": ["Student"]
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:00Z"
  },
  "error": null
}
```

#### `GET /v1/me`

- **Purpose:** fetch actor identity, role assignments, and effective scopes.
- **Trace:** FR-31 to FR-33.

### 4.2 Academic setup endpoints

#### `POST /v1/terms`

- **Purpose:** create an academic term.
- **Roles:** AcademicAdmin.
- **Trace:** FR-01.

Request:

```json
{
  "code": "2026-1",
  "name": "Hoc ky 1 nam 2026",
  "startDate": "2026-08-01",
  "endDate": "2026-12-31",
  "isActive": true
}
```

#### `POST /v1/courses`

- **Purpose:** create or update course catalog records used by class sections.
- **Roles:** AcademicAdmin.
- **Trace:** FR-02.

Request:

```json
{
  "code": "SE101",
  "name": "Nhap mon Cong nghe Phan mem",
  "facultyId": "uuid",
  "creditUnits": 3
}
```

#### `POST /v1/class-sections`

- **Purpose:** create a term course offering with assigned lecturer, default room, and optional schedule template.
- **Roles:** AcademicAdmin; DepartmentAdmin only if explicitly scoped and enabled.
- **Trace:** FR-03, FR-06.

Request:

```json
{
  "sectionCode": "SE101-01",
  "termId": "uuid",
  "courseId": "uuid",
  "lecturerUserId": "uuid",
  "defaultRoomId": "uuid",
  "scheduleTemplate": {
    "dayOfWeek": "Monday",
    "startTime": "08:00",
    "durationMinutes": 120
  }
}
```

Success response returns the section plus generated `Scheduled` session count when session generation is requested.

#### `GET /v1/class-sections?termId=&lecturerUserId=&page=&pageSize=`

- **Purpose:** list class sections by scope.
- **Roles:** Lecturer, DepartmentAdmin, AcademicAdmin.
- **Trace:** FR-03, FR-10, BR-19.

#### `POST /v1/enrollments/import`

- **Purpose:** import enrollment rows (CSV).
- **Roles:** AcademicAdmin; DepartmentAdmin if allowed by policy.
- **Trace:** FR-04, BR-06.

Request:

```json
{
  "classSectionId": "uuid",
  "rows": [
    {
      "studentCode": "SE170001"
    }
  ]
}
```

Response includes row-level error summary and accepted count.

Import response (`200` with row errors allowed):

```json
{
  "data": {
    "classSectionId": "uuid",
    "acceptedRows": 58,
    "rejectedRows": [
      {
        "rowNumber": 12,
        "code": "StudentNotFound",
        "message": "Khong tim thay ma sinh vien."
      }
    ]
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:00Z"
  },
  "error": null
}
```

### 4.3 Session lifecycle endpoints

#### `GET /v1/class-sessions?classSectionId=&date=&state=`

- **Purpose:** list sessions for lecturer/admin dashboards.
- **Trace:** FR-06, FR-10.

#### `POST /v1/class-sessions/{sessionId}/open`

- **Purpose:** transition `Scheduled` -> `Open`.
- **Roles:** Lecturer (assigned section), AcademicAdmin.
- **Trace:** FR-07, BR-01.

Response includes current QR token preview metadata.

Request body is optional. If provided, it may include a room override for legitimate timetable changes:

```json
{
  "roomId": "uuid"
}
```

Success response (`200`):

```json
{
  "data": {
    "classSessionId": "uuid",
    "state": "Open",
    "openedAt": "2026-07-02T08:00:00Z",
    "qr": {
      "expiresAt": "2026-07-02T08:00:30Z",
      "qrPayload": "opaque-or-short-url"
    }
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:00:00Z"
  },
  "error": null
}
```

#### `POST /v1/class-sessions/{sessionId}/close`

- **Purpose:** transition `Open` -> `Closed`.
- **Roles:** Lecturer (assigned section), AcademicAdmin.
- **Trace:** FR-08, FR-09, BR-02, BR-13.

Side effects:
- invalidate active QR tokens;
- finalize unresolved students as `Absent` per policy;
- write audit entry.

Success response includes summary counts for lecturer confirmation:

```json
{
  "data": {
    "classSessionId": "uuid",
    "state": "Closed",
    "closedAt": "2026-07-02T09:30:00Z",
    "summary": {
      "present": 45,
      "late": 5,
      "manualPresent": 2,
      "absent": 8
    }
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T09:30:00Z"
  },
  "error": null
}
```

### 4.4 QR token and check-in endpoints

#### `GET /v1/class-sessions/{sessionId}/qr/current`

- **Purpose:** lecturer fetches current valid QR metadata.
- **Roles:** Lecturer (assigned), AcademicAdmin.
- **Trace:** FR-11, FR-14.

Response:

```json
{
  "data": {
    "classSessionId": "uuid",
    "tokenState": "Valid",
    "expiresAt": "2026-07-02T08:32:30Z",
    "qrPayload": "opaque-or-short-url"
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:01Z"
  },
  "error": null
}
```

#### `POST /v1/check-ins`

- **Purpose:** student submits attendance attempt.
- **Roles:** Student.
- **Trace:** FR-16, FR-17, FR-18, FR-22, FR-23; BR-03 to BR-12; AC-04, AC-08, AC-11.

Request:

```json
{
  "qrToken": "opaque-token",
  "clientTimestamp": "2026-07-02T08:32:10+07:00",
  "gps": {
    "latitude": 10.762622,
    "longitude": 106.660172,
    "accuracyMeters": 24.5
  }
}
```

Success response (`200`):

```json
{
  "data": {
    "outcome": "Success",
    "attendanceStatus": "Present",
    "classSessionId": "uuid",
    "checkInAt": "2026-07-02T08:32:11Z"
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:11Z"
  },
  "error": null
}
```

Rule-failure response (`422`):

```json
{
  "data": null,
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:12Z"
  },
  "error": {
    "code": "OutOfRadius",
    "message": "Vi tri hien tai ngoai pham vi cho phep.",
    "details": {
      "distanceMeters": 162.8,
      "allowedRadiusMeters": 100
    }
  }
}
```

### 4.5 Attendance ledger endpoints

#### `GET /v1/class-sessions/{sessionId}/attendance`

- **Purpose:** retrieve roster view (`Present`, `Late`, `Pending`, rejected attempts summary).
- **Roles:** Lecturer (assigned), DepartmentAdmin (scoped), AcademicAdmin, SystemAuditor (read-only).
- **Trace:** FR-19, FR-28, FR-32.

Response (`200`):

```json
{
  "data": {
    "classSessionId": "uuid",
    "state": "Open",
    "counts": {
      "present": 30,
      "late": 3,
      "pending": 27,
      "rejectedAttempts": 4
    },
    "rows": [
      {
        "studentUserId": "uuid",
        "studentCode": "SE170001",
        "displayName": "Nguyen Van A",
        "attendanceStatus": "Present",
        "checkInMethod": "QR",
        "checkInAt": "2026-07-02T08:05:00Z",
        "latestAttemptOutcome": "Success"
      }
    ]
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:10:00Z"
  },
  "error": null
}
```

#### `PATCH /v1/class-sessions/{sessionId}/attendance/{studentUserId}`

- **Purpose:** manual correction by lecturer/admin.
- **Roles:** Lecturer within section + edit window; AcademicAdmin override.
- **Trace:** FR-20, FR-21, BR-14 to BR-16, AC-13, AC-14.

Request:

```json
{
  "status": "Manual Present",
  "reason": "Sinh vien co mat nhung loi camera tren thiet bi."
}
```

Allowed `status` values are policy-controlled but must be drawn from `attendanceStatus`. The endpoint rejects a lecturer correction outside assigned section scope (`403 OutOfScope`) or outside edit window (`409 EditWindowExpired` or escalation response per policy). Every accepted mutation writes `AuditLog` with old status, new status, actor, reason, and correlation ID (`FR-29`, `BR-22`).

### 4.6 Reporting and export endpoints

#### `GET /v1/reports/attendance`

- **Purpose:** paginated report query.
- **Roles:** Lecturer, DepartmentAdmin, AcademicAdmin, SystemAuditor(read-only scope).
- **Trace:** FR-28, BR-19.

Query params:
- `termId`, `classSectionId`, `studentUserId`, `status`, `from`, `to`, `sortBy`, `sortOrder`, `page`, `pageSize`.

#### `POST /v1/exports/attendance`

- **Purpose:** create CSV export job within actor scope.
- **Roles:** Lecturer(scoped), DepartmentAdmin(scoped), AcademicAdmin.
- **Trace:** FR-27, FR-30, BR-18, AC-15, AC-17.

Request:

```json
{
  "format": "csv",
  "filters": {
    "termId": "uuid",
    "classSectionId": "uuid",
    "status": "Absent"
  }
}
```

Success response (`202` when generated asynchronously):

```json
{
  "data": {
    "exportJobId": "uuid",
    "status": "Queued",
    "format": "csv"
  },
  "meta": {
    "requestId": "uuid",
    "timestamp": "2026-07-02T08:32:00Z"
  },
  "error": null
}
```

### 4.7 Audit endpoints

#### `GET /v1/audit-logs`

- **Purpose:** query auditable actions.
- **Roles:** AcademicAdmin, ITAdmin(technical context), SystemAuditor.
- **Trace:** FR-30, FR-32, BR-22.

Query parameters: `actorUserId`, `targetType`, `targetId`, `actionType`, `from`, `to`, `page`, `pageSize`. `SystemAuditor` access is read-only and scope-filtered. `ITAdmin` receives technical audit context only unless an explicit academic grant exists.

## 5. Check-in validation contract

### 5.1 Validation order

Check-in API must short-circuit in this order:

1. Authentication (`Unauthenticated`) — BR-05.
2. Session state (`SessionNotOpen` / `SessionClosed`) — BR-01, BR-02.
3. Token integrity and expiry (`ExpiredQr` / invalid) — BR-03, BR-04.
4. Enrollment (`NotEnrolled`) — BR-06.
5. Duplicate success (`DuplicateCheckIn`) — BR-07.
6. GPS policy checks (`GpsRequired`, `GpsDisabled`, `OutOfRadius`, `LowAccuracy`) — BR-08 to BR-10.
7. Status assignment (`Present`/`Late`) — BR-11, BR-12.
8. Attempt logging and audit hooks — BR-23.

### 5.2 Processing guarantees

| Guarantee | Mechanism | Trace |
| --- | --- | --- |
| One success per student per session | DB unique key + idempotent command handling | BR-07, NFR-07 |
| 100% failed attempt reason coverage | mandatory `outcome` and `error.code` mapping | FR-22, AC-18 |
| Correlation across logs | `X-Request-Id` and `correlationId` persisted | FR-30 |

### 5.3 Check-in transaction boundary

`POST /v1/check-ins` is the latency-critical write path. The server evaluates and persists the attempt in one command boundary:

1. Resolve authenticated `Student` actor.
2. Resolve token to `classSessionId` without trusting client-provided session IDs.
3. Read session, token, enrollment, existing attendance, and effective policy.
4. Insert `CheckInAttempt` with terminal outcome.
5. On `Success`, insert or update `AttendanceRecord` to `Present` or `Late`.
6. Emit realtime roster event and audit/compliance event with the same correlation ID.

If the success write conflicts with an existing record, the API returns `409 DuplicateCheckIn` unless the idempotency record proves this is a replay of the same accepted command.

## 6. Authorization model in API layer

### 6.1 Scope resolution

| Role | Scope key used for filtering |
| --- | --- |
| Student | `studentUserId = actorUserId` |
| Lecturer | assigned `classSectionId` set |
| DepartmentAdmin | assigned `facultyId` |
| AcademicAdmin | configured institution scope |
| ITAdmin | technical resources only unless explicit academic grant |
| SystemAuditor | read-only, scoped |

### 6.2 Authorization response behavior

- Return `403` with `OutOfScope` when actor has role but target resource is outside authorized scope.
- Return `403` with `Forbidden` when action is not allowed for role.
- Never return partial restricted datasets for denied requests.

## 7. Idempotency, retry, and rate limits

### 7.1 Idempotency rules

| Endpoint | Idempotency behavior |
| --- | --- |
| `POST /v1/check-ins` | idempotent per (`Idempotency-Key`, actor, token) within short replay window |
| `POST /open` and `/close` | repeated call returns current state and prior result |
| `PATCH attendance` | duplicate key returns already-applied mutation summary |
| `POST /exports/attendance` | duplicate key returns existing export job id |

### 7.2 Rate-limit guidance

| Endpoint group | Suggested limit | Reason |
| --- | --- | --- |
| Check-in submit | high burst per IP + per student controls | class-start peak protection |
| Login | strict per account/IP | brute-force mitigation |
| Export creation | low frequency | heavy resource usage |
| Audit/report queries | moderate | protect DB read capacity |

## 8. Event integration contract

### 8.1 Event names emitted by API writes

| Event | Emitted by | Payload keys |
| --- | --- | --- |
| `SessionOpened` | `/class-sessions/{id}/open` | `sessionId`, `openedAt`, `actorUserId` |
| `SessionClosed` | `/class-sessions/{id}/close` | `sessionId`, `closedAt`, `actorUserId` |
| `CheckInAttemptRecorded` | `/check-ins` | `attemptId`, `outcome`, `sessionId`, `studentUserId` |
| `AttendanceRecorded` | `/check-ins` success path | `attendanceRecordId`, `status`, `sessionId` |
| `AttendanceCorrected` | attendance patch | `oldStatus`, `newStatus`, `reason` |
| `ExportCreated` | export endpoint | `exportJobId`, `scope`, `actorUserId` |

### 8.2 Event guarantees

- At-least-once delivery with idempotent consumers.
- Payload includes `correlationId` and `occurredAt`.
- Audit logging may be synchronous or guaranteed asynchronous, but must remain complete (`FR-29`, `FR-30`).

## 9. API-to-requirement traceability

| API area | FR | BR | AC |
| --- | --- | --- | --- |
| Session open/close endpoints | FR-07, FR-08, FR-09 | BR-01, BR-02, BR-13, BR-21 | AC-01, AC-05, AC-12 |
| QR endpoints | FR-11, FR-12, FR-14 | BR-03, BR-04 | AC-02, AC-03, AC-04 |
| Check-in endpoint | FR-16, FR-17, FR-18, FR-22, FR-23, FR-34, FR-35 | BR-05 to BR-12, BR-23 | AC-06 to AC-11, AC-18 |
| Manual correction endpoint | FR-20, FR-21, FR-29 | BR-14, BR-15, BR-16, BR-22 | AC-13, AC-14, AC-19 |
| Report/export endpoints | FR-27, FR-28, FR-30 | BR-18, BR-19, BR-22 | AC-15, AC-16, AC-17 |
| Audit query endpoint | FR-30, FR-32 | BR-22, BR-23 | AC-19 |

## 10. Future consideration

- GraphQL aggregation layer for complex report filtering.
- Signed, time-limited download links for export artifacts.
- Webhook callbacks for completed exports and policy alerts.
- Per-student challenge-token API after QR scan for higher assurance.
- Dedicated dispute-case APIs for formal appeal lifecycle.
