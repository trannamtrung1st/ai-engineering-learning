# Docker Compose Local Runtime

> **Status:** Canonical harness requirement. `docker-compose.yml` implementation is a follow-up task; policy and completion gates apply now.

## 1. Objective
Define a reproducible local runtime using Docker Compose with two explicit modes:
- **Development:** database container only; API and web run as local Node processes.
- **Full preview:** database + API + web run as built container images.

## 2. Prerequisites (When Implemented)
- Docker Desktop (or compatible Docker Engine + Compose v2)
- Node.js LTS (>= 20) for development mode
- Monorepo workspaces: `apps/api`, `apps/web`, `packages/domain`

## 3. Runtime Modes

### 3.1 Development Mode (DB Only)
Use when iterating on application code with fast reload.

| Component | Runtime |
|---|---|
| PostgreSQL | Docker container (`db` service) |
| API | Local `npm run dev --workspace @we-event/api` |
| Web | Local `npm run dev --workspace @we-event/web` |

Harness commands (see `ai-harness/docs/preview-runtime.md`):
- `npm run aih:dev:db:up` → `docker compose up -d db`
- `npm run aih:dev:db:down` → `docker compose stop db`
- `npm run aih:preview` → `./ai-harness/scripts/preview-stack.sh --mode dev`

### 3.2 Full Preview Mode (Built Images)
Use for end-to-end smoke validation with production-like containers.

| Component | Runtime |
|---|---|
| PostgreSQL | Docker container (`db` service) |
| API | Built image from `apps/api/Dockerfile` |
| Web | Built image from `apps/web/Dockerfile` |

Harness commands (see `ai-harness/docs/preview-runtime.md`):
- `npm run aih:preview:full` → `./ai-harness/scripts/preview-stack.sh --mode full`
- `npm run aih:preview:verify` → `./ai-harness/scripts/verify-stack.sh`
- `npm run aih:preview:down` → `./ai-harness/scripts/preview-stack.sh --down`

## 4. Compose File Contract (`docker-compose.yml`)

Planned file location: repository root.

```yaml
name: we-event

services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: we_event
      POSTGRES_USER: we_event
      POSTGRES_PASSWORD: we_event
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U we_event -d we_event"]
      interval: 5s
      timeout: 5s
      retries: 20

  api:
    build:
      context: .
      dockerfile: apps/api/Dockerfile
    profiles: ["full-preview"]
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      PORT: "3001"
      DATABASE_URL: postgresql://we_event:we_event@db:5432/we_event
    ports:
      - "3001:3001"

  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
    profiles: ["full-preview"]
    restart: unless-stopped
    depends_on:
      api:
        condition: service_started
    environment:
      PORT: "3000"
      API_BASE_URL: http://api:3001
      NEXT_PUBLIC_API_BASE_URL: http://localhost:3001
    ports:
      - "3000:3000"
```

### 4.1 Storage Policy
- **No named volumes.** Database data is ephemeral for local preview.
- Data resets when containers are recreated.
- Suitable for local dev/preview; not for durable local datasets.

### 4.2 Persistence Policy for Harness Runs
- **Development mode (DB only)** is mandatory for harness-driven implementation: API and web run as local Node processes; Postgres runs in the `db` Compose service.
- API must connect via `DATABASE_URL=postgresql://we_event:we_event@localhost:5432/we_event`.
- Migrations must run against this Postgres instance before API startup.

### 4.3 Forbidden Persistence Modes
Harness and guardrails hard-fail implementations that use:
- In-memory stores or module-level `Map`/`Record` repositories as the system of record.
- SQLite, `better-sqlite3`, or embedded JSON-file databases.
- Mock-only repositories without a Postgres adapter.
- Any shortcut that skips schema migrations against Compose Postgres.

### 4.4 Default Ports
| Service | Host port |
|---|---|
| PostgreSQL | 5432 |
| API | 3001 |
| Web | 3000 |

## 5. Image Build Contracts

### 5.1 API Image (`apps/api/Dockerfile`)
Multi-stage build from monorepo root:

1. **deps** — install `@we-event/api` workspace dependencies (includes `@we-event/domain`).
2. **builder** — `npm run build --workspace @we-event/api`.
3. **runner** — production image running `npm run start --workspace @we-event/api`.

Required workspace scripts:
- `build` → compiles to `apps/api/dist/`
- `start` → runs compiled production server

### 5.2 Web Image (`apps/web/Dockerfile`)
Multi-stage Next.js build from monorepo root:

1. **deps** — install `@we-event/web` workspace dependencies.
2. **builder** — `npm run build --workspace @we-event/web` with `output: "standalone"` in `next.config.*`.
3. **runner** — `node apps/web/server.js` from standalone output.

Required workspace scripts:
- `build` → Next.js production build
- `start` → optional for local non-Docker use

### 5.3 Build Context (`.dockerignore`)
Exclude from image build context:
- `.git`, `docs/`, `ai-harness/generated/`
- `node_modules`, `dist`, `.next`, `coverage`
- `.env` files (except `.env.example` as reference)

## 6. Environment Variables

| Variable | Scope | Example |
|---|---|---|
| `DATABASE_URL` | API | `postgresql://we_event:we_event@localhost:5432/we_event` (dev) or `@db:5432` (preview) |
| `PORT` | API / Web | `3001` / `3000` |
| `API_BASE_URL` | Web (server-side) | `http://api:3001` in preview |
| `NEXT_PUBLIC_API_BASE_URL` | Web (browser) | `http://localhost:3001` |
| `JWT_SECRET` | API | local secret (not committed) |
| `TIMEZONE` | API | `UTC` |

## 7. Harness Integration

The AI harness:
- References this spec from `10-local-development-setup.md` and `ai-harness/HARNESS-DESIGN.md`.
- Requires `docker-compose.yml` and `.env.example` with `DATABASE_URL` as completion artifacts.
- Enforces forbidden in-memory/SQLite patterns in `ralph-loop.json` completion criteria.
- Uses canonical preview and startup verification scripts specified in `ai-harness/docs/preview-runtime.md` (`preview-stack.sh`, `verify-stack.sh`). Root npm scripts `aih:preview`, `aih:preview:full`, `aih:preview:verify`, and `aih:preview:down` are defined there and supersede inline command wording in this doc.
- Specifies `runtimeValidation` in `ralph-loop.json` (active when compose and apps exist):

```json
"runtimeValidation": {
  "db": {
    "strategy": "docker-compose",
    "service": "db",
    "healthTimeoutMs": 60000,
    "requiredBeforeApi": true
  },
  "api": {
    "activeWhen": "apps/api",
    "url": "http://localhost:3001/api/v1/health",
    "expectJson": { "status": "ok", "db": "connected" },
    "timeoutMs": 60000
  },
  "web": {
    "activeWhen": "apps/web",
    "url": "http://localhost:3000",
    "expectStatus": 200,
    "timeoutMs": 120000
  }
}
```

`run-checks.sh` enforces DB health and quick API/web probes (`verify-stack.sh --quick`); set `AIH_VERIFY_STACK=1` for full poll against a running preview stack.

Recommended startup timeout for first image build: 180s.

## 8. Non-Goals
- Cloud deployment or orchestration beyond local Compose.
- Persistent local database volumes.
- Bind-mount hot reload inside preview containers.

## 9. Traceability
- Local setup overview: `10-local-development-setup.md`
- Stack recommendation: `12-backend-frontend-tech-stack.md`
- Database baseline: `04-database-design.md`
- NFR-02, NFR-04..NFR-06, NFR-14, NFR-15
