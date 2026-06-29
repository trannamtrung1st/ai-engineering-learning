# We Check — Docker Compose Local Runtime

Canonical local container specification for **We Check** MVP. Defines two runtime modes: **development** (PostgreSQL only) and **full preview** (database + built API + web images). Harness-driven implementation must use Compose Postgres as the sole system of record — no in-memory or SQLite shortcuts.

**Related documents:** [Local development setup](./10-local-development-setup.md) · [Backend / frontend tech stack](./12-backend-frontend-tech-stack.md) · [Database design](./04-database-design.md) · [Testing plan](./11-testing-plan.md)

---

## 1. Objective

Provide reproducible local infrastructure that:

- Starts PostgreSQL 15+ with health checks for integration and E2E tests.
- Supports fast-iteration dev mode (DB in Docker; Node processes on host).
- Supports full-preview mode for smoke validation with production-like containers.
- Enforces persistence guardrails required by the AI harness.

---

## 2. Prerequisites

| Tool | Version |
| --- | --- |
| Docker Desktop or Docker Engine + Compose v2 | Latest stable |
| Node.js LTS | ≥ 20 (development mode) |
| npm workspaces | `apps/api`, `apps/web`, `packages/domain` |

Ensure port **5432** is available or adjust mapping in override file (not committed).

---

## 3. Runtime Modes

### 3.1 Development mode (DB only)

Use during daily feature work with hot reload.

| Component | Runtime |
| --- | --- |
| PostgreSQL | Docker container (`db` service) |
| API | Local `npm run dev --workspace @wecheck/api` |
| Web | Local `npm run dev --workspace @wecheck/web` |

**Harness commands:**

| Script | Action |
| --- | --- |
| `npm run aih:dev:db:up` | `docker compose up -d db` |
| `npm run aih:dev:db:down` | `docker compose stop db` |
| `npm run aih:preview` | `./ai-harness/scripts/preview-stack.sh --mode dev` |

### 3.2 Full preview mode (built images)

Use for pre-pilot smoke tests and CI preview jobs.

| Component | Runtime |
| --- | --- |
| PostgreSQL | Docker container (`db` service) |
| API | Built image from `apps/api/Dockerfile` |
| Web | Built image from `apps/web/Dockerfile` (nginx or Node static) |

**Harness commands:**

| Script | Action |
| --- | --- |
| `npm run aih:preview:full` | `./ai-harness/scripts/preview-stack.sh --mode full` |
| `npm run aih:preview:verify` | `./ai-harness/scripts/verify-stack.sh` |
| `npm run aih:preview:down` | `./ai-harness/scripts/preview-stack.sh --down` |

First full build may take up to **180 seconds** — allow extended health timeout.

---

## 4. Compose File Contract

**File location:** repository root `docker-compose.yml`.

```yaml
name: we-check

services:
  db:
    image: postgres:15-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: wecheck
      POSTGRES_USER: wecheck
      POSTGRES_PASSWORD: wecheck
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wecheck -d wecheck"]
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
      NODE_ENV: production
      DATABASE_URL: postgresql://wecheck:wecheck@db:5432/wecheck
      SESSION_SECRET: ${SESSION_SECRET:-local-preview-secret-change-me}
      CORS_ORIGIN: http://localhost:3000
    ports:
      - "3001:3001"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:3001/api/v1/health || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12

  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
    profiles: ["full-preview"]
    restart: unless-stopped
    depends_on:
      api:
        condition: service_healthy
    environment:
      PORT: "3000"
    ports:
      - "3000:3000"
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:3000 || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 12
```

### 4.1 Service summary

| Service | Image / build | Host port | Profile |
| --- | --- | --- | --- |
| `db` | `postgres:15-alpine` | 5432 | always |
| `api` | `apps/api/Dockerfile` | 3001 | `full-preview` |
| `web` | `apps/web/Dockerfile` | 3000 | `full-preview` |

PostgreSQL version aligns with [04-database-design.md](./04-database-design.md) (15+).

---

## 5. Storage and Persistence Policy

### 5.1 Database volumes (MVP local)

- **No named volume for `db` in default compose** — data is ephemeral across `docker compose down -v`.
- Suitable for local dev, CI, and harness runs where deterministic seed is preferred.
- Developers needing durable local data may create `docker-compose.override.yml` (gitignored) with:

```yaml
services:
  db:
    volumes:
      - wecheck_pg_data:/var/lib/postgresql/data

volumes:
  wecheck_pg_data:
```

### 5.2 Forbidden persistence modes

Harness and guardrails **hard-fail** implementations using:

| Forbidden pattern | Reason |
| --- | --- |
| In-memory `Map` / object stores as system of record | No ACID; fails [NFR-02](../brds/07-non-functional-risk.md) |
| SQLite, `better-sqlite3`, embedded JSON DB | Diverges from production PostgreSQL |
| Mock-only repositories without Postgres adapter | Untestable integration behavior |
| Skipping schema bootstrap against Compose Postgres | Schema drift undetected |

### 5.3 Development mode connection string

API on host must use:

```
DATABASE_URL=postgresql://wecheck:wecheck@localhost:5432/wecheck
```

API in full-preview uses `@db:5432` hostname inside Compose network.

---

## 6. Default Ports

| Service | Host port | Container port |
| --- | --- | --- |
| PostgreSQL | 5432 | 5432 |
| API | 3001 | 3001 |
| Web | 3000 | 3000 |

Browser clients access web at `http://localhost:3000`. API health at `http://localhost:3001/api/v1/health`. Vite dev proxy serves `/api/v1` on port 3000 in development mode.

---

## 7. Image Build Contracts

### 7.1 API image (`apps/api/Dockerfile`)

Multi-stage build from monorepo root:

1. **deps** — `npm ci` with workspace focus `@wecheck/api` and `@wecheck/domain`.
2. **builder** — `npm run build --workspace @wecheck/api`.
3. **runner** — production Node alpine; `npm run start --workspace @wecheck/api`.

Required workspace scripts:

| Script | Output |
| --- | --- |
| `build` | `apps/api/dist/` compiled JavaScript |
| `start` | Production server entrypoint |
| `dev` | Hot reload (local only) |

### 7.2 Web image (`apps/web/Dockerfile`)

Multi-stage build:

1. **deps** — install `@wecheck/web` and `@wecheck/domain`.
2. **builder** — `npm run build --workspace @wecheck/web` producing static assets.
3. **runner** — nginx alpine serving `dist/` **or** Node serving static + proxy to API.

Production web container must serve SPA with fallback to `index.html` for client routes.

Environment at build time for API URL:

```
VITE_API_BASE_URL=http://localhost:3001
```

Browser calls absolute API URL in full-preview; dev mode uses Vite proxy instead.

### 7.3 Build context (`.dockerignore`)

Exclude from image context:

```
.git
docs/
ai-harness/generated/
node_modules
**/dist
**/.next
coverage
.env
.env.local
*.md
```

Include `.env.example` as documentation reference only.

---

## 8. Environment Variables

| Variable | Scope | Dev (host API) | Full preview (container) |
| --- | --- | --- | --- |
| `DATABASE_URL` | API | `postgresql://wecheck:wecheck@localhost:5432/wecheck` | `postgresql://wecheck:wecheck@db:5432/wecheck` |
| `PORT` | API | `3001` | `3001` |
| `SESSION_SECRET` | API | Random secret in `.env` | Compose env / secret |
| `CORS_ORIGIN` | API | `http://localhost:3000` | `http://localhost:3000` |
| `NODE_ENV` | API | `development` | `production` |
| `SEED_ENABLED` | API | `true` | `false` (use migrate + manual seed) |
| `LOG_LEVEL` | API | `debug` | `info` |
| `VITE_API_BASE_URL` | Web build | empty (use proxy) | `http://localhost:3001` |

Root `.env.example` documents all variables for [10-local-development-setup.md](./10-local-development-setup.md).

---

## 9. Health and Readiness

| Endpoint | Expected response | Used by |
| --- | --- | --- |
| `GET /api/v1/health` | `{ "status": "ok", "db": "connected" }` | Compose API healthcheck, harness verify |
| `pg_isready -U wecheck` | exit 0 | Compose DB healthcheck |
| `GET http://localhost:3000` | HTTP 200 | Web healthcheck |

Simulate dependency failure: stop `db` container → API health returns `503` or `"db": "disconnected"` ([NFR-22](../brds/07-non-functional-risk.md)).

---

## 10. Harness Integration

The AI harness references this spec from [10-local-development-setup.md](./10-local-development-setup.md) and `ai-harness/HARNESS-DESIGN.md`.

**Completion artifacts:**

- `docker-compose.yml` at repository root.
- `.env.example` with `DATABASE_URL`.
- `apps/api/Dockerfile` and `apps/web/Dockerfile`.

**Runtime validation** (in `ai-harness/config/ralph-loop.json` when apps exist):

```json
{
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
}
```

`run-checks.sh` enforces DB health before integration tests. Set `AIH_VERIFY_STACK=1` for full poll against running preview stack.

**Forbidden pattern enforcement:** harness completion criteria reject in-memory and SQLite adapters per §5.2.

---

## 11. Operational Commands Reference

| Task | Command |
| --- | --- |
| Start DB only | `docker compose up -d db` |
| Stop all services | `docker compose --profile full-preview down` |
| View DB logs | `docker compose logs -f db` |
| Reset ephemeral DB | `docker compose down -v && docker compose up -d db` |
| Full preview stack | `docker compose --profile full-preview up --build -d` |
| Connect psql | `psql postgresql://wecheck:wecheck@localhost:5432/wecheck` |

---

## 12. Networking Notes for Mobile Testing

Mobile devices cannot reach `localhost` on the developer machine. For check-in testing:

1. Find host LAN IP (`ipconfig getifaddr en0` on macOS).
2. Run Vite with `npm run dev -- --host 0.0.0.0`.
3. Open `http://<LAN-IP>:3000` on phone (same Wi-Fi).
4. Ensure firewall allows inbound 3000/3001.

Full-preview mode binds `0.0.0.0` by default via port mapping.

---

## 13. Non-Goals

| Excluded | Rationale |
| --- | --- |
| Production Kubernetes / Terraform | IT Operations scope |
| Managed cloud database in compose | Local only |
| Bind-mount hot reload inside preview containers | Dev mode uses host Node |
| Vietnam-region mirror registries | Document when hosting locked |

---

## 14. Traceability Matrix

| Concern | NFR | Reference |
| --- | --- | --- |
| Real Postgres for tests | NFR-02 | [11-testing-plan.md](./11-testing-plan.md) |
| Health endpoints | NFR-22 | [12-backend-frontend-tech-stack.md](./12-backend-frontend-tech-stack.md) §3.5 |
| Load test baseline environment | NFR-23 | [11-testing-plan.md](./11-testing-plan.md) §7 |
| Local dev reproducibility | NFR-21 | [10-local-development-setup.md](./10-local-development-setup.md) |

---

## 15. Future Consideration

| Enhancement | Compose impact |
| --- | --- |
| Redis service | Add `redis:7-alpine` for rate limiting |
| Mailhog | Email notification dev testing |
| MinIO | S3-compatible object storage if exports move to files |
| Compose watch (Docker 4.24+) | Sync source into dev containers |
| Persistent volume by default | Trade ephemeral reset for convenience |
