# Backend / Frontend Tech Stack Recommendation (MVP)

## 1. Objective
Define a single, explicit technical stack recommendation for both backend and frontend, aligned with existing We Event MVP constraints and local-first development goals.

## 2. Recommended Stack

### 2.1 Backend
- Runtime: Node.js LTS (>= 20)
- Language: TypeScript
- API style: REST JSON (`/api/v1`)
- Database: PostgreSQL via Docker Compose (`db` service); mandatory for harness-driven implementation
- Validation: schema validation at request boundary + domain rule validation
- Auth: JWT-based credential auth (email/password signup and login) for preview and production; `POST /dev/token` available only when `DEV_AUTH_ENABLED=true` for harness/local shortcuts
- Observability: structured logs with `requestId`, dedicated audit log stream for critical actions

### 2.2 Frontend
- Language/UI: React + TypeScript
- Framework: Next.js App Router
- Styling: Tailwind CSS with semantic tokens
- Components: headless accessible primitives (Radix UI or equivalent)
- Forms: React Hook Form + Zod
- Server state: TanStack Query
- Data grid/table: TanStack Table (or equivalent lightweight utility)
- Charts: lightweight chart library for organizer KPI views
- Listing pages: server-driven pagination via TanStack Query; `DataTable` and card grids use API `page`/`pageSize`/`total` metadata (not client-only slicing of a full dataset when the backing API is paginated)

## 3. Why This Is Recommended
- Keeps one language (TypeScript) across frontend and backend for faster iteration and shared domain types.
- Matches local-first goals and deterministic validation/testing requirements.
- Supports state-heavy workflows (registration, waitlist, check-in, eligibility) with strict typing and clear API contracts.
- PostgreSQL provides safer concurrency behavior for capacity/waitlist race-condition testing.
- Frontend stack already aligns with UI/UX recommendations and accessibility-first component strategy.

## 4. Mandatory Guardrails
- Backend is server-authoritative for registration, check-in, attendance, and eligibility states.
- No business rule bypass in controllers/UI; domain invariants must be enforced in backend services.
- In-memory, SQLite, and mock-only persistence are forbidden; all data access must go through Postgres migrations and queries.
- Every critical state/config transition must be audit logged (actor, reason, before/after, timestamp).
- Local runtime requires Docker Compose Postgres as specified in `13-docker-compose-local-runtime.md`.

## 5. Suggested Monorepo Layout (When Implementing)
- `apps/api` for backend service
- `apps/web` for frontend app
- `packages/domain` for shared state enums/rule identifiers/contracts
- `packages/config` for shared lint/tsconfig/environment helpers

This structure is recommended for maintainability, but not required for initial MVP bootstrap.

## 6. Non-Goals (Current Phase)
- Cloud deployment topology
- CI/CD infrastructure design
- Service mesh / microservice decomposition
- Mobile-native stack decisions

## 7. Traceability
- System scope and architecture assumptions: `00-system-overview.md`
- Module/domain boundaries: `02-module-breakdown.md`
- Database baseline and constraints: `04-database-design.md`
- API pagination contract: `05-api-design.md` §3
- Local runtime constraints: `10-local-development-setup.md`
- Docker Compose local runtime spec: `13-docker-compose-local-runtime.md`
- Frontend framework recommendation source: `../ui-ux/02-ui-framework-tech-stack.md`
