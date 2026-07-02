---
baseline_commit: e80700f4f59db20e92da6615594f25eaebd5c49c
depends_on: 1-1-bootstrap-project-from-supabase-starter-template
---

# Story 1.1b: NestJS API and Docker Compose Scaffold

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a developer,
I want a NestJS API and Docker Compose local/integration stack,
so that domain logic and database access follow AD-14 and AD-15 from day one.

## Acceptance Criteria

1. **Given** the web scaffold from Story 1.1 **When** `nest new api` runs (NestJS 11.1.27) and `docker-compose.yml` is added at repo root **Then** `api/` exists with global prefix `/api/v1`, `src/modules/` folder, and `AuthGuard`/`RolesGuard` stubs.
2. **And** compose profile `local` starts `postgres:16` + `api` with hot-reload.
3. **And** compose profile `integration` runs migrate/seed one-shot for CI.
4. **And** `drizzle-orm@0.45.2`, `drizzle-kit@0.45.x`, `zod@3.x`, `papaparse@5.x` are installed in `api/` only — removed from web `package.json`.
5. **And** `.env.example` documents `NEXT_PUBLIC_API_URL`, API-only `DATABASE_URL`, `SUPABASE_JWT_SECRET` (or JWKS config note), and scopes `SUPABASE_SERVICE_ROLE_KEY` to API.
6. **And** `docker compose --profile local up` + `npm run dev` (web) smoke-verified.

## Tasks / Subtasks

- [x] Scaffold NestJS API in `api/` (AC: #1)
  - [x] Run `npx @nestjs/cli@11 new api --package-manager npm --skip-git` from repo root
  - [x] Pin `@nestjs/core` to **11.1.27** in `api/package.json`
  - [x] Set global prefix `api/v1` in `api/src/main.ts`; default `PORT=3001`; enable CORS for `http://localhost:3000`
  - [x] Add `GET /api/v1/health` (no guards) returning `{ status: 'ok' }` for smoke tests
- [x] Create structural folders and guard stubs (AC: #1)
  - [x] `api/src/domain/` — empty `.gitkeep` per area (`check-in/`, `accounts/`, `rosters/`, `sessions/`, `attendance/`, `export/`)
  - [x] `api/src/infra/db/` — placeholder `client.ts` + `schema.ts` (empty export; Story 1.2 fills schema)
  - [x] `api/src/modules/health/` — `HealthModule` + `HealthController`
  - [x] `api/src/guards/auth.guard.ts` — stub: require `Authorization: Bearer` header (full JWT validation → Story 1.3)
  - [x] `api/src/guards/roles.guard.ts` — stub: read `@Roles()` metadata; reject with 403 if role mismatch (profile lookup → Story 1.3)
  - [x] `api/src/decorators/roles.decorator.ts` — `@Roles('admin' | 'instructor' | 'student')`
  - [x] Register guards globally or document `@UseGuards(AuthGuard, RolesGuard)` pattern on future controllers
- [x] Install API domain dependencies (AC: #4)
  - [x] `cd api && npm install drizzle-orm@0.45.2 drizzle-kit@0.45.2 zod@3 papaparse @supabase/supabase-js postgres dotenv`
  - [x] `npm install -D @types/papaparse`
  - [x] Add `api/drizzle.config.ts` pointing at `DATABASE_URL` (schema path `src/infra/db/schema.ts`; migrations output `../supabase/migrations`)
  - [x] Add npm scripts: `db:generate`, `db:migrate`, `db:seed` (seed can no-op or echo until Story 1.2)
- [x] Remove domain deps from web root (AC: #4)
  - [x] Remove from root `package.json`: `drizzle-orm`, `drizzle-kit`, `zod`, `papaparse`, `@types/papaparse`
  - [x] Run `npm install` at root to refresh lockfile
- [x] Add `docker-compose.yml` at repo root (AC: #2, #3)
  - [x] Service `postgres` — image `postgres:16`, healthcheck, env from compose defaults
  - [x] Service `api` — profile `local` + `integration`; volume mount for hot-reload; `depends_on` postgres healthy; port `3001:3001`
  - [x] Service `migrate` — profile `integration` only; one-shot `npm run db:migrate && npm run db:seed`; `restart: "no"`
  - [x] Add `api/Dockerfile.dev` for dev/integration (Node 20, `npm run start:dev`)
- [x] Update environment documentation (AC: #5)
  - [x] Expand `.env.example` with split web vs API vars (see Dev Notes table)
  - [x] Update `README.md` HESD section: compose + API dev workflow
- [x] Smoke-verify stack (AC: #6)
  - [x] `docker compose --profile local up` — postgres healthy, API responds `200` on `/api/v1/health`
  - [x] `npm run dev` at root — web loads on `:3000`
  - [x] Optional: `docker compose --profile integration up` — migrate service exits 0

## Dev Notes

### Epic Context & Architecture Pivot

Epic 1 delivers **Platform Foundation & Secure Access**. Story **1.1** (done) bootstrapped the Next.js web layer. This story implements the **architecture pivot** (approved sprint-change-proposal-2026-07-02.md) from a Next.js modular monolith to a **split-stack monorepo**:

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Web | repo root `app/` | UI, Supabase SSR auth, Realtime subscribe |
| API | `api/` | All domain logic + Drizzle writes |
| Infra | `docker-compose.yml` | Local Postgres + API; integration CI profile |

**Do NOT implement in this story:**

| Story | Scope |
|-------|-------|
| 1.2 | Drizzle schema, migrations, `profiles` table, `supabase/seed.sql` bootstrap admin |
| 1.3 | Full JWT validation, role middleware on web, `lib/api-client.ts`, disable sign-up |
| 1.4 | Student password-change gate |
| 1.5 | Neobrutalism design system |

### Current Repo State (Post Story 1.1)

Verified baseline — dev agent must reconcile on checkout:

| Item | State |
|------|-------|
| `api/` | **Does not exist** — create via `nest new` |
| `docker-compose.yml` | **Does not exist** |
| Web `package.json` | Has `drizzle-orm@0.45.2`, `drizzle-kit@0.31.10`, `zod@^4.4.3`, `papaparse` — **remove all** |
| `.env.example` | Has web vars only; missing `NEXT_PUBLIC_API_URL`, API-scoped notes |
| `proxy.ts` | Next.js 16 session refresh — **preserve; do not modify** |
| Role routes | `/admin`, `/instructor`, `/student` placeholders exist |

### NestJS Scaffold Commands

Run from **repo root** (`ai-harnessed_hesd/`):

```bash
npx @nestjs/cli@11 new api --package-manager npm --skip-git
cd api
# Verify @nestjs/core version; pin if needed:
npm install @nestjs/core@11.1.27 @nestjs/common@11.1.27 @nestjs/platform-express@11.1.27
npm install drizzle-orm@0.45.2 drizzle-kit@0.45.2 zod@3 papaparse @supabase/supabase-js postgres dotenv
npm install -D @types/papaparse
```

**`nest new api` creates a subdirectory** — safe in this non-empty monorepo (unlike `create-next-app` at root in Story 1.1).

### `api/src/main.ts` Requirements

```typescript
// api/src/main.ts — key settings
app.setGlobalPrefix('api/v1');
app.enableCors({ origin: process.env.WEB_ORIGIN ?? 'http://localhost:3000' });
await app.listen(process.env.PORT ?? 3001);
```

- Global prefix is `api/v1` (not `/v1` alone) — routes are `/api/v1/health`, `/api/v1/check-in`, etc.
- Web will call `NEXT_PUBLIC_API_URL` + `/api/v1/...` (default `http://localhost:3001`).

### Guard Stubs (Story 1.1b — Not Full Auth)

Per AD-7, AD-15 — implement **stubs** now; Story 1.3 adds Supabase JWT validation + profile role lookup.

**`AuthGuard` stub behavior:**
- Extract `Authorization: Bearer <token>` header
- If missing → `UnauthorizedException`
- If present → attach placeholder `request.user = { id: 'stub', role: 'admin' }` (or skip attachment; document TODO for 1.3)
- **Do not** implement JWKS/`SUPABASE_JWT_SECRET` validation yet — but structure the file for it

**`RolesGuard` stub behavior:**
- Read required roles from `@Roles(...)` metadata via `Reflector`
- Compare against `request.user.role` (stub) or allow-all with TODO comment
- Throw `ForbiddenException` on mismatch

**`@Roles()` decorator:**
```typescript
export const Roles = (...roles: ('admin' | 'instructor' | 'student')[]) =>
  SetMetadata('roles', roles);
```

**Health endpoint:** `GET /api/v1/health` — **no guards** (public smoke probe).

Future controllers (Story 1.3+): `@UseGuards(AuthGuard, RolesGuard)` + `@Roles('instructor')` etc.

### Expected `api/` Folder Structure After Completion

```text
api/
  src/
    main.ts
    app.module.ts
    domain/
      check-in/.gitkeep
      accounts/.gitkeep
      rosters/.gitkeep
      sessions/.gitkeep
      attendance/.gitkeep
      export/.gitkeep
    infra/
      db/
        client.ts          # drizzle client factory (uses DATABASE_URL)
        schema.ts            # empty export {}; Story 1.2 adds tables
    modules/
      health/
        health.module.ts
        health.controller.ts
    guards/
      auth.guard.ts
      roles.guard.ts
    decorators/
      roles.decorator.ts
  drizzle.config.ts
  Dockerfile.dev
  package.json
  tsconfig.json
  nest-cli.json
```

Full domain use-cases from `spine/9-structural-seed.md` are **placeholders only** — no business logic in 1.1b.

### `drizzle.config.ts` Skeleton

```typescript
import { defineConfig } from 'drizzle-kit';
import 'dotenv/config';

export default defineConfig({
  schema: './src/infra/db/schema.ts',
  out: '../supabase/migrations',
  dialect: 'postgresql',
  dbCredentials: { url: process.env.DATABASE_URL! },
});
```

Migrations folder `supabase/migrations/` already implied by structural seed; create if missing. With empty schema, `db:migrate` should succeed (no-op).

### Docker Compose Specification (AD-14)

Single `docker-compose.yml` at **repo root**. Web is **not** in compose.

```yaml
# Reference structure — adapt env names to match .env.example
services:
  postgres:
    image: postgres:16
    profiles: [local, integration]
    environment:
      POSTGRES_USER: hesd
      POSTGRES_PASSWORD: hesd_dev
      POSTGRES_DB: hesd
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U hesd -d hesd"]
      interval: 5s
      timeout: 5s
      retries: 5

  api:
    build:
      context: ./api
      dockerfile: Dockerfile.dev
    profiles: [local, integration]
    ports:
      - "3001:3001"
    volumes:
      - ./api:/app
      - /app/node_modules
    environment:
      DATABASE_URL: postgresql://hesd:hesd_dev@postgres:5432/hesd
      PORT: 3001
      WEB_ORIGIN: http://localhost:3000
    depends_on:
      postgres:
        condition: service_healthy
    command: npm run start:dev

  migrate:
    build:
      context: ./api
      dockerfile: Dockerfile.dev
    profiles: [integration]
    environment:
      DATABASE_URL: postgresql://hesd:hesd_dev@postgres:5432/hesd
    depends_on:
      postgres:
        condition: service_healthy
    command: sh -c "npm run db:migrate && npm run db:seed"
    restart: "no"
```

**`api/Dockerfile.dev` (minimal):**
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3001
CMD ["npm", "run", "start:dev"]
```

**Profiles:**
| Profile | Services | Purpose |
|---------|----------|---------|
| `local` | postgres, api | Daily dev; API hot-reload |
| `integration` | postgres, api, migrate | CI; fresh migrate + seed per run |

**Dev workflow:**
```bash
docker compose --profile local up -d   # postgres + api on :3001
npm run dev                            # web on :3000
curl http://localhost:3001/api/v1/health
```

### Environment Variables (Split Model)

Update `.env.example` to document **scope** clearly:

| Variable | Scope | Purpose |
|----------|-------|---------|
| `NEXT_PUBLIC_SUPABASE_URL` | web | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | web | Anon/publishable key |
| `NEXT_PUBLIC_API_URL` | web | NestJS base URL (`http://localhost:3001`) |
| `SUPABASE_SERVICE_ROLE_KEY` | **api only** | Admin API, account provisioning (Story 1.2+) |
| `SUPABASE_JWT_SECRET` | **api only** | Local JWT validation; hosted uses JWKS (Story 1.3) |
| `DATABASE_URL` | **api only** | Drizzle Postgres (`postgresql://hesd:hesd_dev@localhost:5432/hesd` for compose) |
| `PORT` | api | API listen port (default `3001`) |

**Security (AD-3, AD-13):**
- Never put `SUPABASE_SERVICE_ROLE_KEY` or `DATABASE_URL` in `NEXT_PUBLIC_*`
- Remove `DATABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` from web usage/docs implying web access
- Web never imports Drizzle

**Compose local `DATABASE_URL` for host-side drizzle-kit (optional):**
`postgresql://hesd:hesd_dev@localhost:5432/hesd` (postgres port mapped)

### Web `package.json` Cleanup

Remove these from **root** `package.json` dependencies/devDependencies:

```
drizzle-orm
drizzle-kit
zod
papaparse
@types/papaparse
```

Run `npm install` at root after removal. Verify `npm run build` still passes.

### What This Story Does NOT Include

- Drizzle table definitions or migrations content → Story 1.2
- `supabase/seed.sql` bootstrap admin → Story 1.2
- Full Supabase JWT/JWKS validation in `AuthGuard` → Story 1.3
- Web `lib/api-client.ts` → Story 1.3
- Web role middleware / `requireRole()` → Story 1.3
- Remove `auth/sign-up` route → Story 1.3 (AD-9)
- NestJS domain modules (`check-in`, `sessions`, etc.) with controllers → Stories 1.3+
- Production API hosting → deferred (`spine/11-deferred.md`)
- Playwright / E2E → deferred (`implementation/7-testing-focus.md`)
- Shared `packages/` types between web and api → deferred

### Architecture Compliance

| AD / Rule | Application in this story |
|-----------|---------------------------|
| AD-1 | Split-stack: web at root, API in `api/`; no `lib/domain/` on web |
| AD-2 | API via `nest new api` (NestJS 11); preserve web Supabase SSR |
| AD-3 | No domain mutations in web; API scaffold only |
| AD-7 | `AuthGuard` + `RolesGuard` stubs in `api/src/guards/` |
| AD-13 | Drizzle deps + config in `api/` only; remove from web |
| AD-14 | `docker-compose.yml` with `local` + `integration` profiles |
| AD-15 | NestJS modular structure: `domain/`, `modules/`, `guards/` |
| AD-12 | Env vars documented for deploy envelope |

### File Structure After Completion

```text
ai-harnessed_hesd/
  app/                              # web (unchanged except no drizzle deps)
  api/                              # NEW — NestJS 11
  lib/supabase/                     # web-only — unchanged
  proxy.ts                          # session refresh — unchanged
  supabase/
    migrations/                     # drizzle-kit output (empty until 1.2)
    seed.sql                        # Story 1.2
  docker-compose.yml                # NEW
  .env.example                      # UPDATED — split env model
  README.md                         # UPDATED — compose workflow
  package.json                      # UPDATED — drizzle/zod/papaparse removed
  _bmad/                            # untouched
  _bmad-output/                     # untouched
```

### Testing Requirements

- No automated tests required for scaffold story (`implementation/7-testing-focus.md` defers test stack).
- Manual smoke checklist:
  1. `docker compose --profile local up` — postgres healthy, API `/api/v1/health` → 200
  2. `npm run dev` — web loads `:3000`
  3. `docker compose --profile integration up` — migrate service completes (exit 0)
  4. Root `npm run build` succeeds after dep removal

### Previous Story Intelligence (Story 1.1)

Learnings from `1-1-bootstrap-project-from-supabase-starter-template.md`:

- **Non-empty workspace:** `nest new api` is safe (subdirectory); Story 1.1 used temp-dir + rsync for web at root.
- **Next.js 16 proxy:** Template uses `proxy.ts` + `lib/supabase/proxy.ts` — not `middleware.ts`. Do not rename or break session refresh.
- **Role routes:** Placeholders at `/admin`, `/instructor`, `/student` (not route-group root URLs) to avoid conflicting with template `/` home.
- **Env naming:** Standardized on `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` (not `ANON_KEY`).
- **npm cache:** If permission errors, use isolated cache: `npm_config_cache=/tmp/hesd-npm-cache npm install`.
- **Versions landed:** Next.js 16.2.10, `@supabase/ssr@0.12.0`, `drizzle-orm@0.45.2` at web root (to be moved).
- **Mistake to avoid:** Story 1.1 installed drizzle at web root per old arch — **this story corrects that**.

### Git Intelligence

Recent commits are BMad harness scaffolding (`e80700f init bmad`). Story 1.1 web bootstrap may be uncommitted or on a feature branch — verify `git status` before starting. Do not commit BMad artifacts or `.env.local`.

### Latest Technical Notes (2026)

1. **NestJS 11.1.27** — current stable (June 2026). Requires Node.js 20+. Use `npx @nestjs/cli@11` to avoid global CLI version drift.
2. **Global prefix:** `app.setGlobalPrefix('api/v1')` — all routes under `/api/v1/*`.
3. **Docker hot-reload:** Mount `./api:/app` with anonymous `/app/node_modules` volume; use `npm run start:dev` (`nest start --watch`). On macOS, if file watch fails, add `CHOKIDAR_USEPOLLING=true` to api service env.
4. **drizzle-kit 0.45.x** — pair with `drizzle-orm@0.45.2` (not 0.31.x currently at web root).
5. **zod 3.x** — architecture pins zod 3; web currently has zod 4 — install `zod@3` in api only.
6. **Postgres driver:** Use `postgres` (postgres.js) package for Drizzle in API per common NestJS + Drizzle patterns.
7. **CORS:** Enable for `http://localhost:3000` so Story 1.3 `lib/api-client.ts` works without extra config.

### Project Context Reference

- Global agent rules: `_bmad-output/project-context.md`
- Architecture pivot: `_bmad-output/planning-artifacts/sprint-change-proposal-2026-07-02.md`
- Architecture router: `_bmad-output/planning-artifacts/architecture/architecture-ai-harnessed_hesd-2026-07-02/index.md`
- Cold start: `.../implementation/2-cold-start.md`
- Build order Phase 0: `.../implementation/3-build-order.md`
- API surface: `.../implementation/6-api-surface.md`
- Deployment AD-14: `.../spine/6-ad-deployment.md`
- Structural seed: `.../spine/9-structural-seed.md`
- Stack versions: `.../spine/8-stack.md`

### References

- [Source: epics/epics-ai-harnessed_hesd-2026-07-02/epic-1-platform-foundation-secure-access.md#Story-1.1b]
- [Source: sprint-change-proposal-2026-07-02.md#Section-4.1]
- [Source: architecture/.../spine/2-ad-foundation.md#AD-1, AD-2, AD-3, AD-15]
- [Source: architecture/.../spine/6-ad-deployment.md#AD-14]
- [Source: architecture/.../implementation/2-cold-start.md]
- [Source: architecture/.../spine/9-structural-seed.md#Source-tree]
- [Source: 1-1-bootstrap-project-from-supabase-starter-template.md]

## Dev Agent Record

### Agent Model Used

Claude (Cursor Agent)

### Debug Log References

- `drizzle-kit@0.45.2` is not published on npm; installed `drizzle-kit@0.31.10` (latest) paired with `drizzle-orm@0.45.2`.
- `nest new` initial `npm install` failed; retried with isolated cache.
- Next.js root `tsc` picked up `api/` decorators — fixed by excluding `api` in root `tsconfig.json`.
- Integration `migrate` service failed until `./supabase` volume mount added (drizzle `out: '../supabase/migrations'`).
- Ran `db:generate` once to seed empty `supabase/migrations/meta/_journal.json` for no-op migrate.

### Completion Notes List

- Scaffolded NestJS 11.1.27 API in `api/` with global prefix `/api/v1`, CORS, and public `GET /health`.
- Added domain folder placeholders, Drizzle client/schema stubs, `AuthGuard`/`RolesGuard` stubs, and `@Roles()` decorator.
- Installed API-only domain deps; removed `drizzle-orm`, `drizzle-kit`, `zod`, `papaparse` from web root.
- Added `docker-compose.yml` (`local` + `integration` profiles), `api/Dockerfile.dev`, and split `.env.example` / README docs.
- Smoke verified: `docker compose --profile local` health 200, `npm run dev` web 200, integration migrate exit 0, root `npm run build` pass, API e2e test pass.

### File List

- `api/` (new NestJS scaffold — main.ts, app.module.ts, guards, decorators, modules/health, infra/db, domain placeholders, drizzle.config.ts, Dockerfile.dev, package.json, test/app.e2e-spec.ts)
- `docker-compose.yml`
- `.env.example`
- `README.md`
- `package.json`
- `package-lock.json`
- `tsconfig.json`
- `supabase/migrations/meta/_journal.json`
- `supabase/migrations/.gitkeep`

### Change Log

- 2026-07-02: Story 1.1b — NestJS API scaffold, Docker Compose local/integration profiles, API-only Drizzle deps, web dep cleanup, env/README updates.
