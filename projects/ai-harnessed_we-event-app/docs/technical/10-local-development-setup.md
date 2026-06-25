# Local Development Setup

## 1. Objective
Provide a reproducible local environment for building and validating We Event MVP behavior with emphasis on business-rule integrity.

## 2. Prerequisites
- Node.js LTS (recommended >= 20)
- Package manager: npm/pnpm/yarn (project default preferred)
- Git and shell tools
- Docker Desktop (or compatible Docker Engine + Compose v2) — required for PostgreSQL local runtime (see `13-docker-compose-local-runtime.md`)

## 3. Local Environment Variables
Minimum required variables (example names):
- `DATABASE_URL`
- `APP_PORT`
- `JWT_SECRET` (or local auth secret)
- `DEV_AUTH_ENABLED=true|false` (enables `POST /dev/token` for harness/local; credential auth always available when users table is seeded)
- `UPLOADS_DIR` (filesystem path for event cover images; default `./uploads` in dev)
- `TIMEZONE` (recommend UTC for deterministic tests)
- `SEED_ENABLED=true|false`

Rules:
- Do not commit local secrets.
- Provide `.env.example` with non-sensitive defaults.

## 4. Local Runbook
1. Install dependencies.
2. Start database: `npm run aih:dev:db:up` (Docker Compose `db` service only).
3. Run migrations against Postgres (`DATABASE_URL` must point at Compose instance).
4. Seed reference data (organization/users/events).
5. Start API service locally (`npm run dev --workspace @we-event/api`).
6. Start frontend locally (`npm run dev --workspace @we-event/web`).
7. Verify health endpoint and smoke flow.

### 4.1 Docker Compose Runtime
Local container orchestration is specified in `13-docker-compose-local-runtime.md` and is the canonical harness persistence baseline.

| Mode | What runs in Docker | What runs locally |
|---|---|---|
| Development | PostgreSQL only | API + web dev servers |
| Full preview | PostgreSQL + built API + built web images | Nothing |

Root scripts (when `docker-compose.yml` is present):
- `npm run aih:dev:db:up` / `aih:dev:db:down` — DB-only for development
- `npm run aih:preview` / `aih:preview:down` — full preview with built images

Do not use in-memory repositories, SQLite, or non-Compose Postgres shortcuts for harness-driven work.

## 5. Seed Data Strategy
Seed data should include:
- 1 organization.
- 3 actor personas (`OrganizerAdmin`, `OrganizerStaff`, `Participant`) with credential-based user records (email + password hash).
- At least 2 events:
  - one with available seats,
  - one full with waitlist enabled.
- registration/check-in/feedback fixtures for transition testing.

Optional: one event with a seeded cover image for UI smoke testing.

## 6. Local Validation Guardrails
- Fail startup when schema migration is pending.
- Fail startup when enum definitions mismatch DB.
- Enforce strict request schema validation in dev mode.
- Fail startup when `DATABASE_URL` does not target the Compose Postgres instance.

## 7. Local Observability Basics
- Structured logs with `requestId`.
- Optional local metrics endpoint.
- Separate logs for domain audit trail simulation.

## 8. Developer Workflow
- Make changes in small slices.
- Run unit tests before integration tests.
- Run business-rule scenario suite before merge.
- Verify no canonical state name drift from design docs.

## 9. Known Local Risks and Mitigations
- **Race conditions**: run concurrent registration tests on PostgreSQL.
- **Clock drift**: use fixed clock abstraction in tests.
- **Data contamination**: reset DB between scenario test runs.

## 10. Non-Goals (This Phase)
- Cloud deployment scripts.
- Infrastructure-as-code.
- Production scaling and traffic management.

## 11. BRD Traceability
- NFR-02, NFR-04..NFR-06, NFR-14, NFR-15, NFR-17, NFR-18
- AC-01..AC-17 via local validation workflows
