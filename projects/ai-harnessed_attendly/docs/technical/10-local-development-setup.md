# Attendly — Local Development Setup

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-system-overview.md](./00-system-overview.md) · [05-api-design.md](./05-api-design.md) · [11-testing-plan.md](./11-testing-plan.md) · [12-backend-frontend-tech-stack.md](./12-backend-frontend-tech-stack.md) · [13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md)

## 1. Purpose

This document standardizes local development setup for Attendly MVP to ensure reproducible environments across contributors.

## 2. Development prerequisites

### 2.1 Required tools

| Tool | Recommended version |
| --- | --- |
| Node.js | 20.x LTS |
| pnpm (or npm) | latest stable |
| PostgreSQL client | 15+ compatible |
| Docker Desktop | latest stable |
| Git | latest stable |

### 2.2 OS support

Local development should work on:
- macOS (primary)
- Linux (supported)
- Windows via WSL2 (supported with Docker Desktop)

## 3. Repository bootstrap

### 3.1 Initial setup

1. Clone repository.
2. Install dependencies (`pnpm install` or `npm install` depending on project choice in [12-backend-frontend-tech-stack.md](./12-backend-frontend-tech-stack.md)).
3. Copy environment templates into local `.env` files.
4. Start local runtime dependencies (database/cache) via Docker Compose.
5. Run migrations and seed data.
6. Start backend and frontend services.

### 3.2 Environment files

At minimum:
- `.env.backend`
- `.env.frontend`
- `.env.test`

No secrets should be committed; use `.env.example` templates.

## 4. Local service topology

### 4.1 Core services for development

| Service | Purpose | Default local port |
| --- | --- | --- |
| Backend API | check-in/session/report endpoints | 8080 |
| Frontend app | student + lecturer + admin UI | 3000 |
| PostgreSQL | primary persistence | 5432 |
| Redis (optional) | cache/pubsub/realtime support | 6379 |

### 4.2 Startup order

1. PostgreSQL
2. Redis (if used)
3. Backend API
4. Frontend app

## 5. Database setup

### 5.1 Local database tasks

| Task | Requirement |
| --- | --- |
| Create dev database | one local DB per developer |
| Run schema migrations | mandatory before backend start |
| Seed baseline data | include term/course/section/student fixtures |
| Verify constraints | ensure unique attendance and enrollment keys exist |

### 5.2 Seed minimum dataset

The local seed should include:
- 1 active term
- at least 1 course and 1 class section
- 1 lecturer, 3+ students
- active enrollment rows
- 1 class session in `Scheduled` and 1 in `Open` for workflow tests

## 6. Runtime configuration

### 6.1 Required backend environment variables

| Variable | Description |
| --- | --- |
| `APP_ENV` | `development` |
| `API_PORT` | backend listen port |
| `DATABASE_URL` | PostgreSQL connection string |
| `REDIS_URL` | Redis connection string (if enabled) |
| `JWT_SECRET` | local signing secret |
| `QR_TOKEN_TTL_SECONDS` | default `30` |
| `DEFAULT_GPS_RADIUS_METERS` | default `100` |
| `LOG_LEVEL` | `debug` for local |

### 6.2 Required frontend environment variables

| Variable | Description |
| --- | --- |
| `VITE_API_BASE_URL` (or equivalent) | backend base URL |
| `VITE_APP_NAME` | `Attendly` |
| `VITE_LOCALE_DEFAULT` | `vi-VN` |

## 7. Local workflow commands

### 7.1 Common commands (example convention)

| Command intent | Example |
| --- | --- |
| install deps | `pnpm install` |
| run backend dev server | `pnpm dev:api` |
| run frontend dev server | `pnpm dev:web` |
| run migrations | `pnpm db:migrate` |
| run seeds | `pnpm db:seed` |
| run lint | `pnpm lint` |
| run tests | `pnpm test` |

Exact script names may vary by implementation; keep this document aligned with actual package scripts.

## 8. Developer quality gates

Before creating a PR:
1. Lint passes.
2. Unit/integration tests pass.
3. Basic end-to-end check-in flow verified locally.
4. No hard-coded credentials.
5. Migration files reviewed for backward compatibility.

Trace: AC-01 to AC-19 plus AC-20 to AC-25 smoke subset.

## 9. Troubleshooting guide

### 9.1 Frequent local issues

| Issue | Likely cause | Action |
| --- | --- | --- |
| check-in always `SessionNotOpen` | session seed is `Scheduled` | open session via API/UI |
| frequent `ExpiredQr` in dev | clock drift or stale QR view | sync system time, refresh QR |
| `NotEnrolled` for seeded user | mismatched student IDs | inspect enrollment seed data |
| migration failure | schema drift | reset local DB and re-run migrations |
| CORS errors in frontend | API URL misconfigured | verify frontend env points to local backend |

### 9.2 Reset workflow

When local state is corrupted:
1. Stop services.
2. Recreate DB containers/volumes.
3. Run migration + seed.
4. Restart API/UI.

## 10. Cross-link to local runtime container setup

Container orchestration details and sample compose topology are in [13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md).

## 11. Requirement traceability for local setup

| Local setup area | FR IDs | BR IDs | AC IDs | NFR IDs |
| --- | --- | --- | --- | --- |
| Session open/close and check-in smoke setup | FR-07, FR-08, FR-16, FR-22, FR-23 | BR-01, BR-02, BR-11, BR-12, BR-23 | AC-01, AC-02, AC-03, AC-04, AC-11, AC-12, AC-18 | NFR-01, NFR-06 |
| Enrollment and eligibility fixtures | FR-04, FR-17, FR-18 | BR-06, BR-07 | AC-07, AC-08 | NFR-07 |
| GPS policy local validation | FR-34, FR-35 | BR-08, BR-09, BR-10 | AC-09, AC-10 | NFR-11, NFR-12 |
| Manual fallback and correction checks | FR-20, FR-21, FR-29 | BR-14, BR-15, BR-16, BR-22 | AC-13, AC-14, AC-19, AC-25 | NFR-10, NFR-17 |
| Report/export and audit local checks | FR-27, FR-28, FR-30, FR-32 | BR-18, BR-19, BR-22 | AC-15, AC-16, AC-17, AC-19 | NFR-09, NFR-13 |

## 12. Future consideration

- Preconfigured devcontainer for one-command onboarding.
- Synthetic load profile command for class-start concurrency checks.
- One-command seed profiles for lecturer/admin/student demo personas.

## 13. MVP boundary note

- Local setup must support all Must capabilities in [../brds/01-stakeholders-scope.md](../brds/01-stakeholders-scope.md) §2.1 before optional Should capabilities.
- Any local-only helper service that is not required for MVP behavior should remain optional and disabled by default.

## 14. Developer onboarding checklist

New contributors are ready when all items below pass locally:

| Item | Done when |
| --- | --- |
| Environment setup | backend and frontend env files are populated from templates |
| Dependency boot | local DB and optional cache are healthy |
| Data readiness | migrations + seeds complete without manual fixes |
| Core workflow smoke | open session -> scan QR -> successful check-in -> close session works |
| Governance smoke | manual correction and CSV export produce expected audit records |
