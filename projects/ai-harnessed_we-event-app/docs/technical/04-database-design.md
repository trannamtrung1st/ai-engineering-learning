# Database Design

## 1. Storage Choice (Local-First)
Mandatory local MVP database:
- PostgreSQL via Docker Compose (`db` service) for transactional integrity, indexing, and concurrent rule testing.
- API connects through `DATABASE_URL=postgresql://we_event:we_event@localhost:5432/we_event` in development mode.

Forbidden persistence modes (harness hard fail):
- In-memory stores, module-level `Map`/`Record` repositories, or process-local caches used as the system of record.
- SQLite or other embedded databases.
- JSON-file or mock-only repositories without a Postgres adapter.
- Any dev shortcut that skips schema bootstrap against the Compose Postgres instance.

### 1.1 Data Access Pattern
- **No ORM** — repositories execute raw SQL via the `pg` driver and a shared connection pool.
- **Per-module schema** — DDL co-located with each domain module; applied lazily on first use (idempotent bootstrap, not versioned migration tooling).
- **Transactional boundaries** — multi-table operations (registration + waitlist, cancellation + promotion, check-in + status transition) run in a single database transaction.

## 2. Logical Schema
Core tables:
- `organizations`
- `users`
- `roles`
- `user_roles`
- `events`
- `event_rule_configs`
- `registrations`
- `waitlist_entries`
- `checkin_records`
- `feedback_submissions`
- `certificate_eligibilities`
- `audit_logs`

**Status history** is not a separate table — `GET /events/{eventId}/status-history` projects registration state-change rows from `audit_logs`.

## 3. Key Columns and Constraints
### `users`
- `id` PK (UUID)
- `email` unique, not null (normalized lowercase)
- `password_hash` not null
- `display_name` not null
- `created_at`, `updated_at`

Constraints:
- unique index on `lower(email)`

### `user_roles`
- `id` PK
- `user_id` FK → `users.id`
- `role` enum (`OrganizerAdmin`, `OrganizerStaff`, `Participant`)
- `organization_id` FK nullable (required for organizer roles)
- `assigned_event_ids` uuid[] nullable (staff scope)

Constraints:
- unique `(user_id, role, organization_id)` where applicable

### `events`
- `id` PK
- `organization_id` FK
- `state` enum (`Draft`, `Published`, `RegistrationOpen`, `RegistrationClosed`, `InProgress`, `Completed`, `Archived`, `Cancelled`)
- `start_at`, `end_at`
- `cover_image_key` nullable (storage key for uploaded cover image)
- `cover_image_updated_at` nullable
- `created_by`, `updated_by`

Constraints:
- `start_at < end_at`

### `event_rule_configs`
- `event_id` PK/FK (1:1 with event)
- `capacity` int
- `waitlist_enabled` bool
- `registration_open_at`, `registration_close_at`
- `checkin_open_at`, `checkin_close_at`
- `feedback_required` bool
- `feedback_open_at`, `feedback_close_at`
- `version` int

Constraints:
- `capacity >= 0`
- registration/check-in/feedback windows all have `open < close`
- `version` increments on every critical change

### `registrations`
- `id` PK
- `event_id` FK
- `participant_id` FK → `users.id` (authenticated participant identity)
- `state` enum (`Requested`, `Registered`, `Waitlisted`, `Rejected`, `CancelledByUser`, `CancelledByOrganizer`, `CheckedIn`, `Attended`, `Absent`, `Expired`)
- `requested_at`
- `cancelled_at` nullable
- `status_reason_code` nullable
- `status_reason_text` nullable

Constraints and indexes:
- Unique active registration index on `(event_id, participant_id)` for active states.
- Index on `(event_id, state)` for capacity and status queries.

### `waitlist_entries`
- `id` PK
- `event_id` FK
- `registration_id` FK unique
- `position` int
- `enqueued_at`
- `promoted_at` nullable
- `expired_at` nullable

Constraints:
- unique `(event_id, position)` for stable queue order

### `checkin_records`
- `id` PK
- `registration_id` FK unique
- `event_id` FK
- `checkin_at`
- `method` enum (`Staff`, `Self`)
- `operator_id` nullable (required for staff check-in)

Constraints:
- one valid check-in record per registration

### `feedback_submissions`
- `id` PK
- `event_id` FK
- `registration_id` FK unique
- `participant_id` FK
- `submitted_at`
- `payload_json`

### `certificate_eligibilities`
- `id` PK
- `event_id` FK
- `registration_id` FK unique
- `result` enum (`PendingEvaluation`, `Eligible`, `NotEligible`, `Revoked`)
- `reason_code`
- `reason_text`
- `evaluated_at`
- `overridden_by` nullable

### `audit_logs`
- `id` PK
- `event_id` FK nullable
- `entity_type`
- `entity_id`
- `action`
- `actor_id`
- `actor_role`
- `reason_code` nullable
- `reason_text` nullable
- `before_json`
- `after_json`
- `occurred_at`

Constraints:
- append-only policy
- non-null actor and action

## 4. Capacity and Concurrency Guardrails
- Registration acceptance uses transaction + row lock on event rule config.
- Seat assignment operation computes registered count in-transaction.
- Promotion from waitlist uses `ORDER BY position ASC` with lock to avoid double promotion.
- Cancellation and promotion run atomically.

### Pagination index support
- `events.start_at` — default sort for `GET /events`.
- `waitlist_entries(event_id, position)` — FIFO queue paging.
- `registrations.updated_at` — registration list and `GET /me/registrations` paging.
- `audit_logs.occurred_at` — governance list paging (`audit-logs`, `status-history` endpoints).

## 5. Suggested DDL Guardrail Snippets
```sql
-- Unique active registration constraint example (PostgreSQL partial index)
CREATE UNIQUE INDEX uq_active_registration
ON registrations(event_id, participant_id)
WHERE state IN ('Requested', 'Registered', 'Waitlisted', 'CheckedIn');
```

```sql
-- Query accelerator for capacity checks
CREATE INDEX idx_reg_event_state
ON registrations(event_id, state);
```

```sql
-- Paginated registration and my-registrations sorts
CREATE INDEX idx_reg_event_updated
ON registrations(event_id, updated_at DESC);
CREATE INDEX idx_reg_participant_updated
ON registrations(participant_id, updated_at DESC);
```

## 6. Data Retention (Local MVP)
- Keep all audit and state history for testability.
- Do not hard-delete business records in MVP.
- Soft-delete user profile only if privacy handling is added later.

## 7. BRD Traceability
- BR-01..BR-13, BR-17..BR-22
- FR-06..FR-17, FR-20, FR-23, FR-24, FR-28..FR-36
- AC-01..AC-07, AC-11, AC-12, AC-13, AC-15..AC-17
- NFR-16, NFR-17, NFR-18 (pagination indexes in §4)
