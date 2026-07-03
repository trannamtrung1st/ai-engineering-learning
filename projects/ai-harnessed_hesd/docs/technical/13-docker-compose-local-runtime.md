# Attendly — Docker Compose Local Runtime

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [10-local-development-setup.md](./10-local-development-setup.md) · [11-testing-plan.md](./11-testing-plan.md) · [12-backend-frontend-tech-stack.md](./12-backend-frontend-tech-stack.md) · [04-database-design.md](./04-database-design.md)

## 1. Purpose

This document specifies the local Docker Compose runtime topology for Attendly MVP development and testing.

## 2. Local container runtime goals

| ID | Goal |
| --- | --- |
| DC-01 | One-command startup for core dependencies |
| DC-02 | Reproducible environment across developers |
| DC-03 | Predictable local ports and service discovery |
| DC-04 | Easy reset/reseed for testing workflows |

## 3. Compose topology

### 3.1 Core services

| Service name | Role | Container port | Host port |
| --- | --- | --- | --- |
| `postgres` | primary database | 5432 | 5432 |
| `redis` | cache/pubsub (optional but recommended) | 6379 | 6379 |
| `api` | backend service | 8080 | 8080 |
| `web` | frontend service | 3000 | 3000 |

### 3.2 Optional local tooling services

| Service name | Purpose |
| --- | --- |
| `pgadmin` | local DB inspection |
| `mailhog` | test email capture (if auth flows require email) |
| `test-runner` | isolated integration test execution |

## 4. Environment and networking

### 4.1 Compose network

- Use a dedicated bridge network (e.g., `attendly-local-net`).
- Service-to-service references use container names (`postgres`, `redis`, `api`).

### 4.2 Required environment variables

| Service | Required variables |
| --- | --- |
| `api` | `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, `QR_TOKEN_TTL_SECONDS=30`, `DEFAULT_GPS_RADIUS_METERS=100` |
| `web` | `VITE_API_BASE_URL=http://localhost:8080`, `VITE_LOCALE_DEFAULT=vi-VN` |
| `postgres` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` |

## 5. Boot and health sequence

### 5.1 Startup order

1. Start `postgres` and wait for health check.
2. Start `redis` and wait for health check.
3. Run migration/seed step (in `api` startup script or one-off task).
4. Start `api`.
5. Start `web`.

### 5.2 Health checks

| Service | Health check |
| --- | --- |
| `postgres` | `pg_isready` |
| `redis` | `redis-cli ping` |
| `api` | `/health` endpoint |
| `web` | HTTP check on root route |

## 6. Data persistence and reset policy

### 6.1 Local volumes

| Volume | Purpose |
| --- | --- |
| `postgres_data` | database persistence between restarts |
| `redis_data` (optional) | cache persistence for debug scenarios |

### 6.2 Reset workflows

| Operation | Use case |
| --- | --- |
| soft reset (reseed only) | clean test data while preserving schema |
| hard reset (drop volumes) | schema drift or corrupted local state |

After reset, always run migrations and seeds before workflow testing.

## 7. Suggested compose profiles

### 7.1 Development profile

- `postgres`, `redis`, `api`, `web`
- file-watch mode for `api` and `web`

### 7.2 Test profile

- `postgres`, `redis`, `api`
- dedicated test DB name and isolated volume
- no UI container required for API integration suites
- this profile acts as the default local **test stack** for integration and contract tests

### 7.3 Minimal profile

- `postgres`, `api`
- for backend-only debugging where realtime cache is not needed

## 8. Compose operations guidance

### 8.1 Standard operations

| Intent | Command pattern |
| --- | --- |
| start services | `docker compose up -d` |
| stop services | `docker compose down` |
| restart single service | `docker compose restart <service>` |
| view logs | `docker compose logs -f <service>` |
| run migration job | `docker compose run --rm api <migration-command>` |
| run seed job | `docker compose run --rm api <seed-command>` |

### 8.2 Local diagnostics

| Symptom | Quick check |
| --- | --- |
| API cannot connect DB | inspect `DATABASE_URL` and postgres health |
| frequent runtime errors on startup | verify migration and seed step success |
| frontend cannot call API | check `VITE_API_BASE_URL` and exposed ports |

## 9. Security and local policy notes

### 9.1 Local-only assumptions

- Local secrets are non-production and must never be committed.
- TLS termination is optional in local compose, mandatory outside local.
- Test data should remain synthetic and non-sensitive.

### 9.2 Audit and privacy behavior in local runtime

- Failed attempts, corrections, and exports should still be audit-logged in local for realistic testing.
- GPS data handling should follow the same collection boundaries as production logic.

## 10. Testing integration with compose

### 10.1 Integration test execution model

1. Start test profile containers.
2. Run migrations and test seeds.
3. Run integration suite.
4. Tear down containers and clear ephemeral test volume.

### 10.2 Performance smoke test setup

- Use compose profile with API + DB + cache.
- Simulate concurrent check-ins against open session.
- Track latency and success-rate metrics aligned with AC-20/AC-21/AC-22.

### 10.3 Flake management in containerized tests

Containerized CI and local runs should include explicit controls for test flake reduction:

| Control | Expected behavior |
| --- | --- |
| isolated service boot | each run provisions clean DB/cache state to reduce flake from residual data |
| deterministic readiness gates | health checks must pass before test execution to avoid startup-race flake |
| retry discipline | only infrastructure-level retries are allowed; business-logic failures are never masked as flake |
| artifact capture | failed runs persist logs and compose events for flake triage |

## 11. Runtime validation checklist

| Check ID | Validation | Expected result | Trace |
| --- | --- | --- | --- |
| DC-CHK-01 | `postgres` and `redis` pass health checks before API boot | API starts without dependency boot race | FR-22, NFR-16 |
| DC-CHK-02 | migration and seed commands succeed in clean environment | local workflows run with valid fixtures | AC-01, AC-07 |
| DC-CHK-03 | open session + rotating QR works in local runtime | QR TTL/refresh behavior observable | FR-11, AC-02, AC-03 |
| DC-CHK-04 | check-in failures are logged with reason codes | 100% failed-attempt reason coverage in local logs | FR-22, AC-18, NFR-13 |
| DC-CHK-05 | report/export runs only for scoped user roles | no cross-scope leak in local verification | BR-18, BR-19, AC-15, AC-16 |

## 12. Requirement traceability

| Compose runtime area | FR IDs | BR IDs | AC IDs | NFR IDs |
| --- | --- | --- | --- | --- |
| Session and check-in local orchestration | FR-07, FR-08, FR-11, FR-16, FR-22, FR-23 | BR-01, BR-02, BR-03, BR-11, BR-12, BR-23 | AC-01, AC-02, AC-03, AC-04, AC-11, AC-18 | NFR-01, NFR-06 |
| Local policy and GPS verification | FR-34, FR-35 | BR-08, BR-09, BR-10 | AC-09, AC-10 | NFR-11, NFR-12 |
| Manual fallback and correction in local scenarios | FR-20, FR-21, FR-29 | BR-14, BR-15, BR-16, BR-22 | AC-13, AC-14, AC-19, AC-25 | NFR-10, NFR-17 |
| Report/export runtime checks | FR-27, FR-28, FR-30, FR-32 | BR-18, BR-19, BR-22 | AC-15, AC-16, AC-17 | NFR-09, NFR-13, NFR-16 |

## 13. Future consideration

- Devcontainer integration that wraps compose startup and toolchain installation.
- Separate compose overrides for CI and local performance replay.
- Optional tracing stack (e.g., OpenTelemetry collector) in local profile.

## 14. MVP boundary note

- Compose defaults should boot only services required for MVP Must workflows (session open/close, check-in, manual correction, export, audit).
- Additional tooling containers are optional and must not be required for baseline contributor onboarding.

## 15. Local runtime readiness checklist

Use this quick gate before sharing branches for review:

| Checkpoint | Pass criteria |
| --- | --- |
| dependency health | postgres and redis health checks stay green after cold start |
| migration stability | clean boot + migrate + seed runs without manual intervention |
| workflow sanity | one end-to-end class session flow executes successfully |
| export and audit sanity | CSV export works and audit entries are queryable |
| teardown/reset | compose down/up cycle reproduces the same healthy state |
