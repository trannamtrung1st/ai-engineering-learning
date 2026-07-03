# Attendly — Backend/Frontend Tech Stack

**Product:** Attendly (*Smart Campus Attendance*)  
**Domain:** Digital campus attendance and class-session check-in for universities and schools  
**Related docs:** [00-system-overview.md](./00-system-overview.md) · [02-module-breakdown.md](./02-module-breakdown.md) · [04-database-design.md](./04-database-design.md) · [05-api-design.md](./05-api-design.md) · [10-local-development-setup.md](./10-local-development-setup.md)

## 1. Purpose

This document defines the recommended MVP technology stack for Attendly backend and frontend, including rationale and constraints.

## 2. Stack selection principles

| ID | Principle | Rationale |
| --- | --- | --- |
| TS-01 | Prioritize predictable delivery over novelty | MVP timeline and operational simplicity |
| TS-02 | Optimize for API correctness and auditability | attendance is compliance-sensitive |
| TS-03 | Keep mobile-web UX fast and clear | student check-in is primary path |
| TS-04 | Use broadly supported tooling | easier hiring and maintenance |

## 3. Recommended backend stack

### 3.1 Runtime and framework

| Layer | Recommendation | Why |
| --- | --- | --- |
| Language | TypeScript | shared types with frontend |
| Runtime | Node.js 20 LTS | mature ecosystem and tooling |
| API framework | NestJS (or Express/Fastify with structured modules) | clear module boundaries and validation |
| Validation | Zod or class-validator | strict schema validation and typed DTOs |

### 3.2 Persistence and messaging

| Layer | Recommendation | Why |
| --- | --- | --- |
| Primary DB | PostgreSQL | strong relational integrity for attendance invariants |
| ORM/query | Prisma or TypeORM (or SQL-first approach) | migration support and productivity |
| Cache/pubsub | Redis (optional MVP, recommended for realtime) | session/channel updates and hot reads |
| Queue | lightweight job queue (Redis-backed) | export jobs and async processing |

### 3.3 Backend platform concerns

| Concern | Recommended approach |
| --- | --- |
| Auth | JWT-based access tokens with role/scope claims |
| RBAC | centralized authorization guard + scope resolver |
| Observability | structured JSON logging + metrics + tracing IDs |
| API docs | OpenAPI generation from source contracts |
| Testing | Jest/Vitest + supertest/integration DB harness |

## 4. Recommended frontend stack

### 4.1 Web UI stack

| Layer | Recommendation | Why |
| --- | --- | --- |
| Framework | React + TypeScript | mature ecosystem and strong DX |
| Build tool | Vite | fast local iteration |
| Routing | React Router | role-based route composition |
| Server-state | TanStack Query | robust API caching/retries |
| Forms/validation | React Hook Form + Zod | reliable input handling |

### 4.2 Next.js option boundary

`Next.js` is an acceptable frontend framework option when the team needs hybrid SSR/CSR pages, but MVP baseline remains client-first check-in delivery with minimal runtime complexity.

| Topic | Baseline choice | Next.js note |
| --- | --- | --- |
| Student check-in flow | client-rendered React routes | keep check-in path fast and deterministic if using Next.js |
| Staff dashboard pages | client-rendered list/detail pages | optional SSR for heavy report pages in Next.js |
| Deployment model | simple static + API split | Next.js app runtime is valid if operationally justified |
| MVP recommendation | React + Vite default | adopt Next.js only when clear FR/NFR benefit is documented |

### 4.3 UI implementation concerns

| Concern | Recommended approach |
| --- | --- |
| Styling | CSS variables + componentized design system integration |
| Accessibility | keyboard and contrast checks for lecturer/admin views |
| i18n | Vietnamese-first copy with key-based localization |
| Realtime updates | WebSocket or SSE for open-session roster |

## 5. Shared and cross-cutting stack

### 5.1 Shared libraries

| Library area | Recommendation |
| --- | --- |
| API types/contracts | shared TypeScript package for DTOs/enums |
| Error codes | shared constant catalog used by API and frontend |
| Date/time | `dayjs` or `date-fns` with UTC handling conventions |
| Validation schemas | shared domain enums and constraint definitions |

### 5.2 DevOps and quality tooling

| Area | Recommendation |
| --- | --- |
| Package manager | pnpm |
| Lint | ESLint + Prettier |
| Commit quality | conventional commit linting optional |
| CI | GitHub Actions (or equivalent) for lint/test/build gates |

## 6. Mapping stack to module architecture

| Module | Primary stack component |
| --- | --- |
| Identity and Access | backend auth module + JWT guards |
| Session Lifecycle | backend domain service + DB transaction |
| Check-in Orchestrator | backend command handler + validation layer |
| Attendance Ledger | backend persistence + audit event hooks |
| Reporting and Export | query service + async job worker |
| Realtime Delivery | Redis pubsub + websocket gateway |
| Frontend student flow | React mobile web check-in pages |
| Frontend staff flow | React admin/lecturer dashboards |

## 7. Versioning and compatibility policy

### 7.1 API compatibility

- API version prefix (`/v1`) required.
- Breaking API changes require new version path or migration strategy.
- Error codes are treated as contract and should not be renamed casually.

### 7.2 Browser support target

- iOS Safari (current major versions used by students)
- Android Chrome (current major versions used by students)
- Chromium-based desktop browser for staff dashboards

## 8. Security and compliance baseline in stack choices

| Requirement | Stack implication |
| --- | --- |
| NFR-08 secure transport | TLS termination in all non-local envs |
| NFR-09 RBAC | scope-aware middleware and query filtering |
| NFR-10 auditability | append-only audit service and immutable writes |
| NFR-11/12 GPS minimization | optional GPS fields and retention jobs |

## 9. MVP stack decision summary

### 9.1 Recommended baseline

- **Backend:** Node.js 20 + TypeScript + NestJS/Fastify + PostgreSQL + optional Redis
- **Frontend:** React + TypeScript + Vite + TanStack Query
- **Testing:** Jest/Vitest + integration DB tests + E2E browser tests
- **Infra for local/dev:** Docker Compose for DB/cache/runtime dependencies

### 9.2 Out-of-scope stack additions for MVP

- Native mobile frameworks.
- Complex event streaming platforms.
- Multi-region distributed data stores.

## 10. Traceability to requirements

| Stack decision area | FR/BR alignment | NFR alignment |
| --- | --- | --- |
| Session and check-in APIs on typed backend modules | FR-07, FR-08, FR-11, FR-16, FR-22, FR-23; BR-01 to BR-04, BR-23 | NFR-01, NFR-03, NFR-06 |
| Transactional relational persistence | FR-18, FR-20, FR-21, FR-29 | NFR-07, NFR-10, NFR-13 |
| Centralized auth + RBAC guards | FR-15, FR-27, FR-28, FR-32; BR-18, BR-19 | NFR-09 |
| Optional cache/pubsub for realtime and burst handling | FR-19, FR-14 | NFR-01, NFR-16 |
| Mobile-web-first frontend stack | FR-16, FR-34, FR-35, FR-37 | NFR-14, NFR-11 |
| Async export/job capabilities | FR-27, FR-30 | NFR-16, NFR-17 |

## 11. Technology decision records (MVP)

| TDR ID | Decision | Alternatives considered | Decision status |
| --- | --- | --- | --- |
| TDR-01 | Use TypeScript end-to-end for backend and frontend | Mixed-language stack | Approved |
| TDR-02 | Use PostgreSQL as source of truth for attendance data | NoSQL-first model | Approved |
| TDR-03 | Use React + Vite for web clients | heavier SSR-first runtime | Approved |
| TDR-04 | Keep Redis optional for MVP baseline, recommended for realtime | mandatory cache cluster | Approved |
| TDR-05 | Keep API contract versioned at `/v1` with stable error codes | unversioned endpoints | Approved |

## 12. Future consideration

- SSO/MFA integration middleware and identity federation adapters.
- Dedicated analytics store for attendance trend modeling.
- Edge caching strategy for high-scale multi-campus deployments.

## 13. MVP boundary note

- Stack choices in this document prioritize delivery of MVP Must capabilities first; Should-scope capabilities (for example advanced policy tooling and extended anti-fraud signals) must not introduce mandatory platform complexity for initial release.
- Technology decisions must preserve the canonical check-in model: session-bound short-lived multi-use QR and one successful attendance record per student/session.

## 14. Stack governance checklist

| Decision gate | Required confirmation |
| --- | --- |
| New dependency proposal | clear mapping to one or more FR/BR/NFR items |
| Runtime/framework change | no regression to check-in latency and idempotency guarantees |
| Frontend library change | mobile-web check-in UX remains first-class on target browsers |
| Infra/tooling addition | local onboarding complexity does not increase for MVP baseline |
