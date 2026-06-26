# Backend / Frontend Tech Stack

## 1. Objective
Document the technical stack for the We Event MVP monorepo, aligned with local-first development goals and harness guardrails.

## 2. Stack

### 2.1 Backend
- Runtime: Node.js LTS (>= 20), TypeScript (ESM)
- Framework: **Fastify** REST API
- API style: REST JSON at `/api/v1`
- Database: **PostgreSQL 16** (Docker Compose) via **`pg`** — no ORM
- Schema: per-module SQL DDL, applied lazily on first use (idempotent bootstrap, not versioned migration tooling)
- Validation: domain rule validators at the service boundary; shared error codes in `@we-event/domain`; Zod on the frontend only
- Auth: JWT bearer + bcrypt password hashing; optional dev token endpoint when `DEV_AUTH_ENABLED=true`
- Cross-cutting concerns: idempotency keys on writes, paginated list envelopes, structured error responses
- Observability: structured logs with `requestId`, append-only audit stream for critical actions
- Testing: Node built-in test runner (unit + integration against real Postgres)

### 2.2 Frontend
- Framework: **Next.js** App Router
- UI: **React** + TypeScript
- Styling: **Tailwind CSS** with semantic CSS variable tokens
- Components: **Radix UI** headless primitives (accessible, composable)
- Forms: **React Hook Form** + **Zod**
- Server state: **TanStack Query**
- Tables: **TanStack Table** with server-driven pagination
- API access: centralized client with role-specific API facades; Next.js rewrites proxy `/api/v1` to the backend
- Auth state: React Context per role namespace; bearer tokens in session storage
- Charts: **deferred** — organizer KPI views use tables and metrics until a chart library is added

## 3. Architecture Style
- **Modular monolith**: vertical domain modules behind a single REST API boundary
- **Shared domain package** (`@we-event/domain`): enums, state machines, and validation error codes shared by API and web
- **Layered backend**: routes → services (orchestration, transactions) → repositories (raw SQL)
- **Server-authoritative**: registration, check-in, attendance, and eligibility states are owned by the API

## 4. Mandatory Guardrails
- No business rule bypass in routes or UI; domain invariants enforced in backend services.
- In-memory, SQLite, and mock-only persistence are forbidden; all data access goes through Postgres.
- Every critical state/config transition must be audit logged (actor, reason, before/after, timestamp).
- Local runtime requires Docker Compose Postgres as specified in `13-docker-compose-local-runtime.md`.

## 5. Monorepo Layout
npm workspaces:

| Package | Role |
|---|---|
| `apps/api` | Fastify REST service |
| `apps/web` | Next.js frontend |
| `packages/domain` | Shared domain types and rules |
| `packages/config` | Shared lint/TypeScript config |
| `tests/e2e` | API scenario acceptance suite |

Default ports: API **3001**, Web **3000**, Postgres **5432**.

Module boundaries and layering: `02-module-breakdown.md` §6.

## 6. Non-Goals (Current Phase)
- Cloud deployment topology
- CI/CD infrastructure design
- Service mesh / microservice decomposition
- Mobile-native stack decisions

## 7. Traceability
- System scope and architecture: `00-system-overview.md`
- Module boundaries: `02-module-breakdown.md`
- Database design: `04-database-design.md`
- API contract: `05-api-design.md` §3
- Local runtime: `10-local-development-setup.md`, `13-docker-compose-local-runtime.md`
- Frontend architecture: `../ui-ux/02-ui-framework-tech-stack.md`
