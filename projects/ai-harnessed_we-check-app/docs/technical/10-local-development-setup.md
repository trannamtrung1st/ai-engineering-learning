# We Check — Local Development Setup

Reproducible local environment for building and validating **We Check** MVP behavior. Emphasizes business-rule integrity, PostgreSQL-backed persistence, and parity with harness guardrails. Docker Compose provides the database; API and web run as local Node processes during active development.

**Related documents:** [Docker Compose local runtime](./13-docker-compose-local-runtime.md) · [Backend / frontend tech stack](./12-backend-frontend-tech-stack.md) · [Database design](./04-database-design.md) · [Testing plan](./11-testing-plan.md) · [Non-functional requirements](../brds/07-non-functional-risk.md)

---

## 1. Objective

Enable engineers and designers to:

- Run the full We Check stack on a single developer machine.
- Seed representative HESD workshop data (100–150 student cohort).
- Execute unit, integration, and E2E tests against real PostgreSQL.
- Validate check-in, GPS, and QR flows before pilot deployment.

Local setup must mirror production semantics (session auth, serializable check-in transactions, Vietnamese messages) without requiring Vietnam-region cloud infrastructure.

---

## 2. Prerequisites

| Tool | Version | Purpose |
| --- | --- | --- |
| Node.js | LTS **≥ 20** | API and web runtime |
| npm | **≥ 10** (bundled with Node) | Monorepo workspaces |
| Docker Desktop or Docker Engine + Compose v2 | Latest stable | PostgreSQL container |
| Git | 2.x | Source control |
| Optional: `psql` client | PostgreSQL 15+ | Manual DB inspection |

**Platform notes:**

- macOS and Linux are primary developer targets.
- Windows via WSL2 is supported with Docker Desktop WSL integration.
- Mobile check-in testing requires physical iOS 15+ or Android 10+ device on same LAN ([NFR-18](../brds/07-non-functional-risk.md)).

---

## 3. Repository Layout (Expected After Bootstrap)

Monorepo structure emitted by harness `repo-bootstrap` step:

| Path | Role |
| --- | --- |
| `apps/api` | Fastify REST API service |
| `apps/web` | Vite + React SPA |
| `packages/domain` | Shared enums, error codes, validation helpers |
| `packages/config` | Shared ESLint / TypeScript config |
| `tests/e2e` | API scenario acceptance suite |
| `docker-compose.yml` | Local PostgreSQL (+ optional full-preview profile) |
| `.env.example` | Non-secret environment template |
| `ai-harness/` | Agent harness scripts and backlog |

Module boundaries: [02-module-breakdown.md](./02-module-breakdown.md).

---

## 4. Environment Variables

Copy `.env.example` to `.env` at repository root. **Never commit `.env`.**

| Variable | Required | Example (local dev) | Scope |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes | `postgresql://wecheck:wecheck@localhost:5432/wecheck` | API |
| `API_PORT` | No | `3001` | API listen port |
| `WEB_PORT` | No | `3000` | Vite dev server |
| `SESSION_SECRET` | Yes | Random 32+ byte hex string | Session cookie signing |
| `NODE_ENV` | No | `development` | API / build |
| `CORS_ORIGIN` | No | `http://localhost:3000` | API CORS |
| `SEED_ENABLED` | No | `true` | Run seed on API startup |
| `DEV_AUTH_BYPASS` | No | `false` | Must remain `false` for check-in path testing |
| `LOG_LEVEL` | No | `debug` | Structured logging |
| `TZ` | No | `UTC` | Deterministic time in tests |

**Rules:**

- `DATABASE_URL` must target Compose Postgres host `localhost:5432` in development mode ([13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md) §4.2).
- API fails fast on startup if database is unreachable ([NFR-22](../brds/07-non-functional-risk.md)).
- Use `UTC` for all timestamps in tests to avoid timezone drift.

---

## 5. First-Time Setup Runbook

### 5.1 Clone and install

```bash
git clone <repository-url>
cd we-check-app
npm install
cp .env.example .env
# Edit .env — set SESSION_SECRET to a random value
```

### 5.2 Start database

```bash
npm run aih:dev:db:up
```

Waits for PostgreSQL health check on port **5432**. See [13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md).

### 5.3 Apply schema and seed

Schema applies via migration tool on first API start (Prisma migrate, Flyway, or equivalent per [04-database-design.md](./04-database-design.md)).

```bash
npm run db:migrate --workspace @wecheck/api
npm run db:seed --workspace @wecheck/api
```

When `SEED_ENABLED=true`, seed runs automatically on `npm run dev`.

### 5.4 Start application services

Terminal 1 — API:

```bash
npm run dev --workspace @wecheck/api
```

Terminal 2 — Web:

```bash
npm run dev --workspace @wecheck/web
```

### 5.5 Verify smoke endpoints

| Check | URL | Expected |
| --- | --- | --- |
| Web home | `http://localhost:3000` | Login page loads |
| API health | `http://localhost:3001/api/v1/health` | `{ "status": "ok", "db": "connected" }` |
| OpenAPI | `http://localhost:3001/api/v1/openapi.json` | OpenAPI document |
| Proxied API (via Vite) | `http://localhost:3000/api/v1/health` | Same health response |

Browser API calls use `/api/v1` on port **3000** (Vite proxy) matching [05-api-design.md](./05-api-design.md) base URL convention.

---

## 6. Seed Data Strategy

Seed script creates deterministic fixtures for workshop scenarios ([AC-01](../brds/08-acceptance-mvp-future.md) through [AC-06](../brds/08-acceptance-mvp-future.md)).

| Entity | Seed content |
| --- | --- |
| Organization context | HESD Cohort A class, Workshop 01 subject |
| Users | 1 `TrainingOfficeAdmin`, 2 `Instructor`, 150 `Student` accounts |
| Credentials | Documented dev passwords in seed output only (not in git) |
| Class assignment | Instructors assigned to HESD cohort |
| Enrollments | All 150 students enrolled in class-subject pair |
| Sessions | 1 `Draft`, 1 `Active` (for QR testing), 1 `Closed` (for reports) |
| Attendance | Mixed `Present`, `Pending`, `Absent` on closed session |
| Policy | Default absence threshold **20%** ([BR-05](../brds/04-business-rules.md)) |

**Reset between test runs:**

```bash
npm run db:reset --workspace @wecheck/api
```

Uses drop/recreate or truncate cascade — never in-memory fallback.

---

## 7. Development Workflows

### 7.1 Instructor flow (local)

1. Login as seeded instructor at `http://localhost:3000/login`.
2. Open `Draft` session → set room GPS (default Ho Chi Minh City test coordinates).
3. Transition to `Active` → verify QR display refreshes every 30 s ([AC-06a](../brds/08-acceptance-mvp-future.md)).
4. Open live attendance monitor (5 s polling).

### 7.2 Student check-in (local + device)

1. On mobile device (same Wi-Fi), navigate to QR deep link or `http://<host-ip>:3000/check-in`.
2. Login as seeded student.
3. Grant camera and GPS permissions.
4. Scan QR from instructor display or paste `tokenId` in dev tools panel.

Use LAN IP instead of `localhost` for mobile browser access.

### 7.3 Admin flow

1. Login as `TrainingOfficeAdmin`.
2. Import sample CSV from `fixtures/roster-sample.csv`.
3. Export attendance CSV from closed session ([FR-13](../brds/03-functional-requirements.md)).

### 7.4 Time manipulation for tests

Use injectable clock in API (`CLOCK_FIXED_AT` env var) to test:

- QR expiry at T + 31 s ([AC-06b](../brds/08-acceptance-mvp-future.md))
- Attendance window auto-close at T + 10 min ([AC-05c](../brds/08-acceptance-mvp-future.md))
- Instructor 24 h edit window ([BR-10](../brds/04-business-rules.md))

---

## 8. Local Validation Guardrails

Startup and harness checks enforce:

| Guardrail | Behavior |
| --- | --- |
| Postgres required | API refuses in-memory or SQLite adapters |
| `DATABASE_URL` host check | Warn if not `localhost:5432` in dev |
| Strict validation | Same Zod/Fastify schemas in dev and production |
| Health endpoint | Reports DB connectivity ([NFR-22](../brds/07-non-functional-risk.md)) |
| CORS | Allows `localhost:3000` only in dev |
| Session cookies | `Secure=false` on localhost; `Secure=true` in preview profile |

Forbidden for harness-driven work ([13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md) §4.3):

- In-memory `Map` repositories as system of record.
- SQLite or JSON file databases.
- Skipping Compose Postgres.

---

## 9. Local Observability

| Signal | Access | Notes |
| --- | --- | --- |
| API logs | stdout JSON | Includes `requestId`, `errorCode` |
| Query logging | `LOG_LEVEL=debug` | Parameterized queries only; no passwords |
| DB inspection | `psql $DATABASE_URL` | Read-only queries recommended |
| Check-in attempts | `SELECT * FROM check_in_attempts ORDER BY created_at DESC LIMIT 20` | Verify outcomes |

Optional: expose `/api/v1/metrics` (Prometheus format) behind dev flag for load test runs ([NFR-23](../brds/07-non-functional-risk.md)).

---

## 10. Common Issues and Mitigations

| Issue | Cause | Fix |
| --- | --- | --- |
| API cannot connect to DB | Compose not running | `npm run aih:dev:db:up` |
| Port 5432 in use | Local Postgres installed | Stop local service or change Compose port mapping |
| Mobile cannot reach dev server | Using `localhost` on phone | Use machine LAN IP; check firewall |
| QR scan fails on HTTP | Camera API requires secure context | Use `vite --host` with HTTPS dev cert or full-preview mode |
| Check-in always `OutOfRadius` | Seed GPS mismatch | Align student mock coords with session room coords in dev panel |
| Session cookie not sent | Cross-origin fetch | Ensure Vite proxy; `credentials: 'include'` |
| Migration drift | Branch switch | `npm run db:reset` |

---

## 11. Developer Quality Checklist (Pre-Merge)

- [ ] `npm run typecheck` passes all workspaces
- [ ] `npm run lint` passes
- [ ] `npm run test:unit` passes
- [ ] `npm run test:integration` passes (DB up)
- [ ] No canonical state enum drift vs [07-state-machines.md](./07-state-machines.md)
- [ ] Error codes match [09-error-handling.md](./09-error-handling.md) catalog
- [ ] Check-in drill: duplicate and parallel cases pass ([AC-09](../brds/08-acceptance-mvp-future.md))

Full gate definitions: [11-testing-plan.md](./11-testing-plan.md) §8.

---

## 12. Non-Goals (This Phase)

| Excluded | Rationale |
| --- | --- |
| Production cloud deployment | IT Operations runbook separate |
| Vietnam-region hosting setup | Pilot infrastructure decision pending ([I-03](../brds/07-non-functional-risk.md)) |
| CI/CD pipeline design | Harness defines local gates first |
| Native mobile app tooling | Mobile web only ([FR-07](../brds/03-functional-requirements.md)) |

---

## 13. Traceability Matrix

| Concern | FR | AC | NFR |
| --- | --- | --- | --- |
| Local auth and check-in | FR-02, FR-07 | AC-02, AC-07 | NFR-10, NFR-18 |
| Roster seed/import | FR-03 | AC-03 | — |
| Session and QR dev flow | FR-04–FR-06 | AC-04–AC-06 | NFR-06 |
| DB-backed persistence | FR-09 | AC-09 | NFR-02 |
| Health and ops | — | — | NFR-22 |
| Load test baseline | — | — | NFR-23 |

---

## 14. Future Consideration

| Enhancement | Local setup impact |
| --- | --- |
| HTTPS dev certificates (mkcert) | Required for realistic iOS camera testing |
| Dockerized API hot-reload | Optional `docker compose --profile dev-full` |
| Seed from production anonymized dump | GDPR / NĐ 13/2023 review required |
| Multi-developer shared dev environment | Remote staging replaces local-only seed |
