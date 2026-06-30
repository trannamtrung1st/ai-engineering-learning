# We Check — Domain Model

Conceptual domain model for **We Check** MVP: entities, attributes, relationships, and invariants. Implementation mapping lives in [technical domain model](../technical/03-domain-model.md) (phase 2).

**Related documents:** [Functional requirements](./03-functional-requirements.md) · [Business rules](./04-business-rules.md) · [State machine](./05-state-machine.md) · [Business workflow](./02-business-workflow.md)

---

## 1. Domain Model Overview

We Check centers on **sessions** where **students** check in via **QR tokens** with **GPS verification**. Supporting aggregates cover identity, roster enrollment, attendance outcomes, audit, and reporting.

| Bounded context | Core aggregates | Primary actors |
| --- | --- | --- |
| Identity and access | `User`, `AuthSession` | All roles |
| Academic structure | `Class`, `Subject`, `Enrollment`, `ClassAssignment` | `TrainingOfficeAdmin`, `Instructor` |
| Live attendance | `Session`, `AttendanceRecord`, `QrToken`, `CheckInAttempt` | `Instructor`, `Student` |
| Compliance and ops | `AttendanceAuditLog`, `ExportAuditLog`, `Notification` | `Instructor`, `TrainingOfficeAdmin` |

### 1.1 Operational constraints (non-entity)

| Constraint | Description | Requirement |
| --- | --- | --- |
| First admin bootstrap | Pre-`User` lifecycle event when `User.count = 0`; not a domain entity — one-time deployment gate | [FR-17](./03-functional-requirements.md), [BR-13](./04-business-rules.md) |

---

## 2. Entity Relationship Diagram

```mermaid
erDiagram
    User ||--o{ Enrollment : "enrolled as Student"
    User ||--o{ ClassAssignment : "teaches as Instructor"
    Class ||--o{ Enrollment : contains
    Subject ||--o{ Enrollment : "scoped to"
    Class ||--o{ Session : "hosts"
    Subject ||--o{ Session : "covers"
    User ||--o{ Session : "creates"
    Session ||--|{ AttendanceRecord : "one per enrolled student"
    User ||--o{ AttendanceRecord : "student"
    Session ||--o{ QrToken : issues
    Session ||--o{ CheckInAttempt : logs
    User ||--o{ CheckInAttempt : "submitted by"
    QrToken ||--o{ CheckInAttempt : "references"
    AttendanceRecord ||--o{ AttendanceAuditLog : "history of"
    User ||--o{ AttendanceAuditLog : "edited by"
    User ||--o{ ExportAuditLog : "exported by"
    User ||--o{ Notification : receives

    User {
        uuid id PK
        string institutionalId UK
        string displayName
        string email UK
        enum role
        boolean active
    }

    Session {
        uuid id PK
        enum status
        datetime scheduledStart
        datetime openedAt
        datetime closedAt
        float roomLatitude
        float roomLongitude
        int gpsRadiusMeters
        string roomName
        string title
    }

    AttendanceRecord {
        uuid id PK
        enum status
        datetime checkedInAt
    }

    QrToken {
        uuid id PK
        enum status
        datetime issuedAt
        datetime expiresAt
    }
```

---

## 3. Entity Catalog

### 3.1 User

Represents a person with system access. MVP roles: `Student`, `Instructor`, `TrainingOfficeAdmin`.

| Attribute | Type | Constraints | Notes |
| --- | --- | --- | --- |
| `id` | UUID | PK | Internal identifier |
| `institutionalId` | String | Unique, required | Student ID or staff ID from institution |
| `displayName` | String | Required | Shown in rosters and reports |
| `email` | String | Unique, required | Login identifier in MVP |
| `role` | Enum | `Student`, `Instructor`, `TrainingOfficeAdmin` | Single role per account in MVP |
| `active` | Boolean | Default true | Deactivated users cannot authenticate ([FR-01](./03-functional-requirements.md)) |
| `createdAt`, `updatedAt` | DateTime | Required | Audit |

**Invariants:** Deactivated user cannot create `CheckInAttempt` or hold valid `AuthSession`.

### 3.2 AuthSession

Server-side authenticated session for web clients.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `userId` | UUID | FK → `User` |
| `expiresAt` | DateTime | Default inactivity 8 hours ([FR-02](./03-functional-requirements.md)) |
| `createdAt` | DateTime | Required |

### 3.3 Class

Academic cohort identifier (e.g., HESD workshop cohort code).

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `code` | String | Unique, required |
| `name` | String | Required |
| `term` | String | Optional |

### 3.4 Subject

Course or workshop module within a program.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `code` | String | Unique per program, required |
| `name` | String | Required |

### 3.5 Enrollment

Links a `Student` user to a `Class` and `Subject`.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `studentId` | UUID | FK → `User` (role Student) |
| `classId` | UUID | FK → `Class` |
| `subjectId` | UUID | FK → `Subject` |
| `enrolledAt` | DateTime | Required |

**Invariants:** Unique (`studentId`, `classId`, `subjectId`). Source: roster import [FR-03](./03-functional-requirements.md).

### 3.6 ClassAssignment

Links an `Instructor` to a `Class` and `Subject` for authorization ([BR-08](./04-business-rules.md#br-08--report-access-by-assignment)).

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `instructorId` | UUID | FK → `User` (role Instructor) |
| `classId` | UUID | FK → `Class` |
| `subjectId` | UUID | FK → `Subject` |

### 3.7 Session

A single scheduled check-in event. State machine: [05-state-machine.md](./05-state-machine.md) §2.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `classId` | UUID | FK → `Class` |
| `subjectId` | UUID | FK → `Subject` |
| `instructorId` | UUID | FK → `User` (role Instructor) |
| `title` | String | Required |
| `roomName` | String | Required |
| `roomLatitude` | Decimal | Required for `Active`; −90..90 |
| `roomLongitude` | Decimal | Required for `Active`; −180..180 |
| `gpsRadiusMeters` | Integer | Default 100; min 20, max 500 |
| `scheduledStart` | DateTime | Required |
| `openedAt` | DateTime | Set on `Active` |
| `closedAt` | DateTime | Set on `Closed` |
| `status` | Enum | `Draft`, `Active`, `Closed`, `Cancelled` |

**Invariants:**

- Cannot transition to `Active` without valid `roomLatitude` and `roomLongitude` ([BR-07](./04-business-rules.md#br-07--session-activation-requires-room-gps)).
- On `Closed`, attendance window end = `scheduledStart` + 10 minutes unless earlier `closedAt` ([BR-01](./04-business-rules.md#br-01--attendance-window-and-auto-close)).

### 3.8 AttendanceRecord

Per-student attendance for one session. State machine: [05-state-machine.md](./05-state-machine.md) §3.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `sessionId` | UUID | FK → `Session` |
| `studentId` | UUID | FK → `User` (role Student) |
| `status` | Enum | `Pending`, `Present`, `Absent`, `Excused`, `Rejected` |
| `checkedInAt` | DateTime | Set when status becomes `Present` via automated check-in |
| `lastUpdatedAt` | DateTime | Required |

**Invariants:**

- Unique (`sessionId`, `studentId`).
- At most one automated transition to `Present` per student per session ([BR-04](./04-business-rules.md#br-04--one-successful-check-in-per-student-per-session)).
- Created in `Pending` for each enrolled student when session is created or opened.

### 3.9 QrToken

Short-lived check-in token bound to a session. State machine: [05-state-machine.md](./05-state-machine.md) §4.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `sessionId` | UUID | FK → `Session` |
| `status` | Enum | `Valid`, `Expired`, `Consumed` |
| `issuedAt` | DateTime | Required |
| `expiresAt` | DateTime | `issuedAt` + 30 seconds |
| `consumedAt` | DateTime | Set on successful check-in |
| `consumedByStudentId` | UUID | FK → `User`, nullable |

**Invariants:**

- Issued only while session `Active`.
- At most one `Consumed` transition per token ([BR-11](./04-business-rules.md#br-11--one-time-use-qr-token-consumption)).

### 3.10 CheckInAttempt

Append-only log of each check-in submission for security and support.

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `sessionId` | UUID | FK → `Session` |
| `studentId` | UUID | FK → `User` |
| `qrTokenId` | UUID | FK → `QrToken` |
| `outcome` | Enum | See [05-state-machine.md](./05-state-machine.md) §5 |
| `attemptedAt` | DateTime | Required |
| `distanceMeters` | Decimal | Nullable; computed at attempt time |
| `spoofFlags` | JSON | Platform hints from client; no long-term raw GPS storage |

**Privacy:** Raw latitude/longitude from the client are used for distance calculation at request time and are not persisted after validation ([BR-02](./04-business-rules.md#br-02--gps-radius-verification), [FR-08](./03-functional-requirements.md)).

### 3.11 AttendanceAuditLog

Records manual attendance changes ([BR-10](./04-business-rules.md#br-10--manual-attendance-edit-window)).

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `attendanceRecordId` | UUID | FK → `AttendanceRecord` |
| `editorId` | UUID | FK → `User` |
| `previousStatus` | Enum | Attendance status |
| `newStatus` | Enum | Attendance status |
| `note` | String | Optional |
| `editedAt` | DateTime | Required |

### 3.12 ExportAuditLog

Records CSV export actions — successful exports and denied attempts ([BR-09](./04-business-rules.md#br-09--csv-export-scoped-by-role)).

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `exportedById` | UUID | FK → `User` (`Instructor` or `TrainingOfficeAdmin`) |
| `filterSummary` | JSON | Class, subject, date range |
| `exportedAt` | DateTime | Required |
| `rowCount` | Integer | Required |

### 3.13 Notification

In-app messages for policy events such as absence warnings ([BR-05](./04-business-rules.md#br-05--automatic-absence-threshold-warning-should)).

| Attribute | Type | Constraints |
| --- | --- | --- |
| `id` | UUID | PK |
| `userId` | UUID | FK → `User` |
| `type` | Enum | e.g., `AbsenceThresholdWarning` |
| `payload` | JSON | Subject code, rate, threshold |
| `readAt` | DateTime | Nullable |
| `createdAt` | DateTime | Required |

---

## 4. Key Relationships and Cardinality

| Relationship | Cardinality | Business meaning |
| --- | --- | --- |
| `Class` — `Enrollment` — `User` (Student) | 1:N:N | Students enroll in a class for a subject |
| `Session` — `Class` + `Subject` | N:1:1 | Each session belongs to one class-subject pair |
| `Session` — `AttendanceRecord` | 1:N | One record per enrolled student per session |
| `Session` — `QrToken` | 1:N | Many tokens over session lifetime (30 s rotation) |
| `AttendanceRecord` — `CheckInAttempt` | 1:N | Student may have multiple failed attempts before success |
| `User` (Instructor) — `ClassAssignment` | 1:N | Instructor may teach multiple class-subject pairs |

---

## 5. Aggregate Boundaries and Consistency

### 5.1 Session aggregate

**Root:** `Session`

**Contains:** `AttendanceRecord` (references), active `QrToken` issuance

**Consistency rules:**

- Opening session validates GPS and creates or confirms `Pending` records for all enrollments matching session class and subject.
- Closing session atomically sets status `Closed` and bulk-updates remaining `Pending` to `Absent`.
- QR issuance stops when session leaves `Active`.

### 5.2 Check-in transaction

**Participating entities:** `QrToken`, `AttendanceRecord`, `CheckInAttempt`

**Atomic outcome:** On `Success`, token → `Consumed`, attendance → `Present`, `CheckInAttempt` logged — in a single database transaction to prevent double consumption.

### 5.3 Roster aggregate

**Root:** `Class` + `Subject` + `Enrollment`

**Owned by:** `TrainingOfficeAdmin` writes; `Instructor` reads assigned subsets.

---

## 6. Domain Events (Conceptual)

| Event | Payload | Downstream effect |
| --- | --- | --- |
| `SessionOpened` | `sessionId`, `openedAt` | Start QR scheduler |
| `SessionClosed` | `sessionId`, `closedAt` | Finalize absences; trigger report availability |
| `CheckInSucceeded` | `sessionId`, `studentId`, `tokenId` | Update live dashboard ([FR-15](./03-functional-requirements.md)) |
| `AttendanceManuallyEdited` | `attendanceRecordId`, audit log | May trigger absence rate recalculation |
| `AbsenceThresholdExceeded` | `studentId`, `subjectId`, rate | Create `Notification` ([BR-05](./04-business-rules.md#br-05--automatic-absence-threshold-warning-should)) |

---

## 7. Reporting Views (Read Model)

Logical projections for [FR-12](./03-functional-requirements.md) and [FR-13](./03-functional-requirements.md) — not separate persisted entities in MVP.

| View | Source entities | Filters |
| --- | --- | --- |
| Session roster report | `AttendanceRecord`, `Session`, `User` | Session ID |
| Class-subject summary | `AttendanceRecord`, `Session`, `Enrollment` | Class code, subject code, date range |
| Student history | `AttendanceRecord`, `Session`, `Subject` | Authenticated student ID only ([FR-14](./03-functional-requirements.md)) |
| CSV export row | Same as class-subject summary | Role-scoped per [BR-09](./04-business-rules.md#br-09--csv-export-scoped-by-role): instructor within assignment; admin institution-wide |

CSV columns: `institutionalId`, `displayName`, `classCode`, `subjectCode`, `sessionDate`, `attendanceStatus`, `checkedInAt`.

---

## 8. Entity-to-Requirement Traceability

| Entity | FR references | BR references |
| --- | --- | --- |
| `User` | FR-01, FR-02 | BR-06 |
| `Enrollment` | FR-03 | — |
| `Session` | FR-04, FR-05 | BR-01, BR-07 |
| `QrToken` | FR-06 | BR-03, BR-11 |
| `AttendanceRecord` | FR-07, FR-11, FR-14 | BR-04, BR-10 |
| `CheckInAttempt` | FR-08, FR-09, FR-10 | BR-02, BR-12 |
| `AttendanceAuditLog` | FR-11 | BR-10 |
| `ExportAuditLog` | FR-13 | BR-09 |
| `Notification` | FR-16 | BR-05 |

---

## 9. Future Consideration

| Enhancement | Model impact |
| --- | --- |
| Academic API sync | `Enrollment` external source ID; sync job entity |
| SSO / IdP | `User` federated identity link; drop local password |
| WiFi BSSID | `Session` optional `expectedBssids[]`; extend `CheckInAttempt` |
| Device fingerprint | New `DeviceProfile` linked to `CheckInAttempt` |
| Room template | Reusable `RoomLocation` entity referenced by `Session` |
| Soft-delete sessions | `Session.deletedAt` instead of hard delete for audit |
