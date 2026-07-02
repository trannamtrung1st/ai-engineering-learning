# Local Runtime Reset and Reseed

**Product:** Attendly  
**Related:** [10-local-development-setup.md](./10-local-development-setup.md) · [13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md)

## Purpose

Document how to recover a clean local Docker runtime when schema drift, corrupted volumes, or stale fixtures block session/check-in workflows (FR-07, FR-16, AC-01, AC-11).

## Stacks

| Stack | Compose file | Reset command |
| --- | --- | --- |
| Dev preview | `docker-compose.yml` | `npm run db:reset` or `./scripts/local-runtime-reset.sh` |
| Test (integration/e2e) | `docker-compose.test.yml` | `npm run aih:test:stack:reset` |

Preview dev DB and the ephemeral test stack use **separate** Postgres volumes and ports (`5432` vs `5433`).

## Soft reset (reseed only)

Preserves schema bookkeeping; re-runs migrate + seed hooks against the existing dev volume.

```bash
./scripts/local-runtime-reset.sh
# or
npm run db:reset
```

Steps performed:

1. Stop preview supervisors (`aih:preview:down`).
2. Ensure `db` and `redis` services are up and healthy.
3. Run `npm run db:migrate` then `npm run db:seed`.

## Hard reset (drop volumes)

Use when migrations fail, schema drifted, or local state is unrecoverable.

```bash
./scripts/local-runtime-reset.sh --hard
# or
npm run db:reset:hard
```

Steps performed:

1. Stop preview stack.
2. `docker compose down -v` — removes `postgres_data` and `redis_data` volumes.
3. Start `db` + `redis`, wait for health checks.
4. Run migrate + seed hooks.

## Test stack reset

Integration and API e2e suites always use the isolated test stack:

```bash
npm run aih:test:stack:reset
npm run test:integration
```

Harness `aih:check` runs `aih:test:stack:reset` automatically before `test:integration` and `test:e2e`.

## Full-preview compose (all services in Docker)

```bash
docker compose --profile full-preview up -d --build
docker compose --profile full-preview run --rm migrate
docker compose --profile full-preview run --rm seed
npm run aih:preview:verify
```

Startup order enforced by Compose: `db` + `redis` healthy → `migrate` → `seed` → `api` healthy → `web`.

## Verification checklist

| Check | Command | Expected |
| --- | --- | --- |
| Dev DB health | `docker compose ps db` | `healthy` |
| Test DB health | `npm run aih:test:stack:status` | `db:healthy` |
| Migrate hook | `npm run db:migrate` | exit 0 |
| Seed hook | `npm run db:seed` | exit 0 |
| API triage | `curl -sf localhost:3001/api/v1/health` | `status: ok`, `db: connected` |

## Traceability

| Workflow | FR | AC | NFR |
| --- | --- | --- | --- |
| Session open/check-in local smoke prerequisites | FR-07, FR-16 | AC-01, AC-11 | NFR-16 |
| Integration isolation | — | — | NFR-16 |
