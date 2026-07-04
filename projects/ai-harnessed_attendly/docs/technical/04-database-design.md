# Attendly — Database Design

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [03-domain-model.md](./03-domain-model.md) · [00-system-overview.md](./00-system-overview.md) · [01-roles-permissions.md](./01-roles-permissions.md) · [../brds/03-functional-requirements.md](../brds/03-functional-requirements.md) · [../brds/04-business-rules.md](../brds/04-business-rules.md) · [../brds/07-non-functional-risk.md](../brds/07-non-functional-risk.md)

## 1. Purpose

This document defines the MVP persistence design for Attendly: relational schema, keys, indexes, constraints, transactional patterns, and data-retention rules required to satisfy FR/BR/NFR acceptance.

## 2. Storage Strategy

### 2.1 Primary data store

| Choice | Decision |
| --- | --- |
| DB engine | PostgreSQL (recommended) |
| Data model | Normalized relational core with selective denormalization for reporting |
| Transaction model | ACID transactions for check-in and attendance writes |
| Time standard | UTC in storage; localized formatting in UI (`vi-VN`) |

### 2.2 Rationale

- Strong consistency is needed for one-success-per-session enforcement (BR-07).
- Relational constraints reduce correctness bugs around enrollment and scope joins.
- Partial indexes and unique constraints support fast validation under check-in peaks.

## 3. Schema Overview

### 3.1 Table groups

| Group | Tables |
| --- | --- |
| Identity | `users`, `user_role_assignments`, `student_profiles`, `lecturer_profiles` |
| Academic structure | `faculties`, `terms`, `courses`, `rooms`, `class_sections`, `enrollments` |
| Session operations | `class_sessions`, `qr_session_tokens` |
| Attendance operations | `check_in_attempts`, `attendance_records` |
| Policy and compliance | `attendance_policies`, `policy_snapshots`, `audit_logs` |

### 3.2 Naming conventions

- Snake_case table and column names.
- Surrogate primary key `id` as UUID for all core tables.
- Foreign keys named `<referenced_table>_id`.
- Enum-like columns use constrained text or PostgreSQL enum types.

## 4. Core Table Specifications

### 4.1 Identity tables

#### `users`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `email` | citext | no | unique |
| `display_name` | text | no |  |
| `is_active` | boolean | no | default true |
| `created_at` | timestamptz | no | default now() |
| `updated_at` | timestamptz | no | default now() |

#### `user_role_assignments`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `user_id` | uuid | no | FK -> `users(id)` |
| `role` | text | no | check in (`Student`,`Lecturer`,`DepartmentAdmin`,`AcademicAdmin`,`ITAdmin`,`SystemAuditor`) |
| `scope_type` | text | no | check in (`Institution`,`Faculty`,`Course`,`ClassSection`,`Self`) |
| `scope_id` | uuid | yes | nullable for institution/self scope |
| `created_at` | timestamptz | no | default now() |

**Unique suggestion:** (`user_id`,`role`,`scope_type`,`scope_id`).

### 4.2 Academic structure tables

#### `faculties`, `terms`, `courses`, `rooms`

Keep these as master tables with unique codes and soft-activation flags.

#### `class_sections`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `section_code` | text | no | unique per term |
| `term_id` | uuid | no | FK -> `terms(id)` |
| `course_id` | uuid | no | FK -> `courses(id)` |
| `lecturer_user_id` | uuid | no | FK -> `users(id)` |
| `default_room_id` | uuid | yes | FK -> `rooms(id)` |
| `capacity` | integer | yes | check > 0 |
| `is_active` | boolean | no | default true |
| `created_at` | timestamptz | no | default now() |

**Unique constraint:** (`term_id`,`section_code`).

#### `enrollments`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `class_section_id` | uuid | no | FK -> `class_sections(id)` |
| `student_user_id` | uuid | no | FK -> `users(id)` |
| `status` | text | no | check in (`Active`,`Dropped`,`Completed`) |
| `enrolled_at` | timestamptz | no | default now() |
| `dropped_at` | timestamptz | yes |  |
| `updated_at` | timestamptz | no | default now() |

**Unique constraint:** (`class_section_id`,`student_user_id`).

### 4.3 Session and token tables

#### `class_sessions`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `class_section_id` | uuid | no | FK -> `class_sections(id)` |
| `room_id` | uuid | yes | FK -> `rooms(id)` |
| `scheduled_start_at` | timestamptz | no |  |
| `scheduled_end_at` | timestamptz | no | check `scheduled_end_at > scheduled_start_at` |
| `state` | text | no | check in (`Scheduled`,`Open`,`Closed`,`Cancelled`) |
| `opened_at` | timestamptz | yes |  |
| `opened_by_user_id` | uuid | yes | FK -> `users(id)` |
| `closed_at` | timestamptz | yes |  |
| `closed_by_user_id` | uuid | yes | FK -> `users(id)` |
| `created_at` | timestamptz | no | default now() |

#### `qr_session_tokens`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `class_session_id` | uuid | no | FK -> `class_sessions(id)` |
| `token_hash` | text | no | unique |
| `state` | text | no | check in (`Valid`,`Expired`,`Invalid`) |
| `issued_at` | timestamptz | no | default now() |
| `expires_at` | timestamptz | no |  |
| `sequence_number` | integer | yes | check >= 0 |

**Constraint:** `expires_at > issued_at`.

### 4.4 Attendance tables

#### `check_in_attempts`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `class_session_id` | uuid | no | FK -> `class_sessions(id)` |
| `student_user_id` | uuid | no | FK -> `users(id)` |
| `qr_session_token_id` | uuid | yes | FK -> `qr_session_tokens(id)` |
| `outcome` | text | no | check against canonical outcome list |
| `submitted_at` | timestamptz | no | default now() |
| `client_timestamp` | timestamptz | yes |  |
| `gps_latitude` | numeric(9,6) | yes |  |
| `gps_longitude` | numeric(9,6) | yes |  |
| `gps_accuracy_meters` | numeric(7,2) | yes | check >= 0 |
| `distance_from_room_meters` | numeric(8,2) | yes | check >= 0 |
| `gps_validation_result` | text | yes | check in (`Pass`,`Fail`,`Skipped`,`Suspicious`) |
| `device_user_agent` | text | yes |  |
| `ip_address` | inet | yes |  |
| `rejection_reason` | text | yes |  |
| `correlation_id` | uuid | yes |  |

#### `attendance_records`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `class_session_id` | uuid | no | FK -> `class_sessions(id)` |
| `class_section_id` | uuid | no | FK -> `class_sections(id)` |
| `student_user_id` | uuid | no | FK -> `users(id)` |
| `status` | text | no | check in (`Pending`,`Present`,`Late`,`Absent`,`Excused`,`Manual Present`) |
| `check_in_method` | text | yes | check in (`QR`,`Manual`,`Admin Correction`) |
| `check_in_at` | timestamptz | yes |  |
| `last_modified_at` | timestamptz | no | default now() |
| `last_modified_by_user_id` | uuid | yes | FK -> `users(id)` |
| `modification_reason` | text | yes |  |
| `source_attempt_id` | uuid | yes | FK -> `check_in_attempts(id)` |

**Critical unique constraint:** (`class_session_id`,`student_user_id`).

### 4.5 Policy and audit tables

#### `attendance_policies`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `scope_type` | text | no | check in (`Institution`,`Faculty`,`Course`,`ClassSection`) |
| `scope_id` | uuid | yes | null only for institution scope |
| `check_in_opening_offset_minutes` | integer | yes | check >= 0 |
| `present_window_minutes` | integer | no | check > 0 |
| `late_window_minutes` | integer | no | check >= 0 |
| `auto_close_enabled` | boolean | no | default true |
| `absence_threshold_percent` | numeric(5,2) | yes | check between 0 and 100 |
| `excused_counts_toward_threshold` | boolean | no | default false |
| `manual_edit_window_hours` | integer | no | check >= 0 |
| `admin_approval_required` | boolean | no | default false |
| `gps_required` | boolean | no | default false |
| `gps_radius_meters` | integer | yes | check > 0 |
| `gps_min_accuracy_meters` | integer | yes | check > 0 |
| `effective_from` | date | yes |  |
| `effective_to` | date | yes | check `effective_to >= effective_from` |
| `is_active` | boolean | no | default true |

#### `policy_snapshots`

Optional immutable capture of resolved policy per session open/check-in runtime.

#### `audit_logs`

| Column | Type | Null | Constraints |
| --- | --- | --- | --- |
| `id` | uuid | no | PK |
| `timestamp` | timestamptz | no | default now() |
| `actor_user_id` | uuid | yes | FK -> `users(id)` |
| `action_type` | text | no | check against allowed audit actions |
| `target_type` | text | no |  |
| `target_id` | uuid | no |  |
| `old_value` | jsonb | yes |  |
| `new_value` | jsonb | yes |  |
| `reason` | text | yes |  |
| `scope_type` | text | yes |  |
| `scope_id` | uuid | yes |  |
| `correlation_id` | uuid | yes |  |
| `ip_address` | inet | yes |  |

## 5. Constraints and Integrity Rules

### 5.1 Database-level integrity

| Rule ID | DB implementation | Requirement trace |
| --- | --- | --- |
| DBR-01 | Unique (`class_session_id`,`student_user_id`) on `attendance_records` | BR-07 |
| DBR-02 | FK from `check_in_attempts.class_session_id` to `class_sessions.id` | BR-01/BR-02 |
| DBR-03 | CHECK for allowed state values in session/token/status columns | FR-07 to FR-13 |
| DBR-04 | Unique `token_hash` in `qr_session_tokens` | BR-04 |
| DBR-05 | Unique (`class_section_id`,`student_user_id`) on `enrollments` | BR-06 |
| DBR-06 | Non-negative numeric checks for GPS metrics | BR-09, BR-10 |
| DBR-07 | `audit_logs` append-only via restricted permissions and no update/delete grants | BR-22 |

### 5.2 Application-enforced integrity (not pure SQL)

- Session must be `Open` before check-in acceptance.
- Token must be in valid TTL window.
- Enrollment status must be `Active`.
- Policy precedence resolution (`ClassSection` > `Course` > `Faculty` > `Institution`).

## 6. Indexing Strategy

### 6.1 Operational indexes

| Table | Index | Purpose |
| --- | --- | --- |
| `class_sessions` | (`class_section_id`,`scheduled_start_at`) | Lecturer session listing |
| `class_sessions` | (`state`,`scheduled_start_at`) | Open/close scheduler and dashboard |
| `qr_session_tokens` | (`class_session_id`,`state`,`expires_at`) | Current token validation |
| `check_in_attempts` | (`class_session_id`,`submitted_at`) | Realtime attempt stream |
| `check_in_attempts` | (`student_user_id`,`submitted_at`) | Student attempt history |
| `attendance_records` | unique (`class_session_id`,`student_user_id`) | Duplicate success prevention |
| `attendance_records` | (`class_section_id`,`status`) | Report and alert queries |
| `enrollments` | (`class_section_id`,`status`) | Eligibility checks |
| `audit_logs` | (`target_type`,`target_id`,`timestamp`) | Forensics |
| `audit_logs` | (`actor_user_id`,`timestamp`) | Compliance actor timeline |

### 6.2 Partial indexes (recommended)

- `check_in_attempts(outcome, submitted_at)` where `outcome <> 'Success'` for rejection analytics.
- `class_sessions(scheduled_start_at)` where `state = 'Open'` for active session scans.

## 7. Transaction Patterns

### 7.1 Student check-in transaction

1. Read `class_sessions` row with lock level appropriate for contention.
2. Validate session state and token validity.
3. Validate enrollment and prior `attendance_records`.
4. Insert `check_in_attempts`.
5. Upsert `attendance_records` for success path only.
6. Insert `audit_logs` entry (or emit event with guaranteed sink).

**Isolation recommendation:** `READ COMMITTED` plus unique-constraint conflict handling for `attendance_records`, with retry on conflict.

### 7.2 Session close transaction

1. Transition session to `Closed`.
2. Bulk upsert `Absent` records for unresolved active enrollments.
3. Invalidate remaining `Valid` QR tokens for session.
4. Write audit event.

### 7.3 Manual correction transaction

1. Authorize actor and scope.
2. Update `attendance_records` status/method/reason.
3. Write `audit_logs` with old/new snapshot.

## 8. Reporting Model

### 8.1 Read model requirements

| Read model | Primary source tables |
| --- | --- |
| Lecturer live roster | `enrollments`, `users`, `attendance_records`, latest `check_in_attempts` |
| Student history | `attendance_records`, `class_sessions`, `class_sections` |
| Section report export | `attendance_records`, `class_sessions`, `users`, `courses`, `terms` |
| Audit review | `audit_logs`, `check_in_attempts` |

### 8.2 Optional performance layer

- Materialized views for term-level reporting can be added after MVP load baselines.
- Rebuild cadence should avoid class-start peak windows.

## 9. Data Retention and Privacy

### 9.1 Retention policy guidance

| Data class | Suggested retention | Notes |
| --- | --- | --- |
| `attendance_records` | Per institutional academic retention | Core academic record |
| `check_in_attempts` (success/failure metadata) | At least one term, longer for disputes | Supports BR-23 |
| Raw GPS (`gps_latitude`,`gps_longitude`) | Short bounded window | NFR-11, NFR-12 |
| `audit_logs` | Compliance-defined long retention | Must remain immutable |

### 9.2 Privacy controls

- Capture GPS only on check-in attempts where policy requires GPS.
- Prefer reporting with derived fields (`distance_from_room_meters`, validation result).
- Restrict raw GPS column access to privileged roles only.

## 10. Migration and Evolution Plan

### 10.1 Initial migration order

1. Identity tables.
2. Academic structure tables.
3. Session and token tables.
4. Attendance tables.
5. Policy and audit tables.
6. Indexes and partial indexes.

### 10.2 Backward-compatible evolution rules

- Add columns as nullable first, then backfill, then enforce constraints.
- Avoid enum hard-coding that blocks future status expansion.
- Version export schemas when adding fields consumed externally.

## 11. Traceability Matrix

| DB area | FR | BR | NFR / AC |
| --- | --- | --- | --- |
| Session and token schema | FR-07 to FR-13 | BR-01 to BR-04 | AC-01 to AC-05 |
| Enrollment and duplicate prevention | FR-17, FR-18 | BR-06, BR-07 | AC-07, AC-08 |
| Attempt and attendance writes | FR-22, FR-23 | BR-11, BR-12, BR-23 | NFR-13, AC-11, AC-18 |
| Close and absent finalization | FR-09 | BR-13, BR-21 | AC-12 |
| Manual correction | FR-20, FR-21 | BR-14 to BR-16 | AC-13, AC-14 |
| Policy persistence | FR-24 to FR-26 | BR-17, BR-20 | AC-09, AC-10 |
| Audit and export persistence | FR-27, FR-29, FR-30 | BR-18, BR-19, BR-22 | AC-16, AC-17, AC-19 |

## 12. Future Consideration

- Native PostgreSQL partitioning for `check_in_attempts` and `audit_logs` by term/month.
- Time-series analytics store for peak attendance telemetry.
- Dedicated dispute evidence table linking attempts, audits, and documents.
- Cryptographic signing for exported CSV artifacts.

