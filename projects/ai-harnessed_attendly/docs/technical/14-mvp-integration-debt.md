# Attendly — MVP Integration Debt (Phase 4)

**Product:** Attendly (*Smart Campus Attendance*)  
**Status:** Open — phase 0–3 feature slices complete; production integration incomplete (~75% MVP readiness)  
**Harness owner docs:** [ai-harness/docs/mvp-integration-gap-register.md](../../ai-harness/docs/mvp-integration-gap-register.md) · [ai-harness/docs/mvp-integration-checklist.md](../../ai-harness/docs/mvp-integration-checklist.md)

## 1. Purpose

Phase 3 delivered isolated backend modules, React surfaces, and test harnesses. This document records **integration debt** that blocks treating the MVP as release-ready on a real preview stack.

Harness agents implement remediation via **phase 4 backlog slices** in `ai-harness/whole-app-backlog.json`.

## 2. Current vs target runtime

| Concern | Current (2026-07-05) | Target |
| --- | --- | --- |
| `AppModule` imports | `HealthModule`, `IdentityModule` only | All MVP modules + `RealtimeModule` |
| Preview API routes | Auth + health; feature paths 404 | Full `/api/v1/*` surface |
| Web data source | Silent harness fixture fallback on 404 | Live Postgres via API (fixtures opt-in) |
| DB lifecycle | `CREATE TABLE IF NOT EXISTS` at repo init | `db:migrate` + `db:seed` scripts |
| Demo accounts | Test fixtures only | `*@attendly.local` / `Password123!` in preview DB |
| JWT env | Code: `ATTENDLY_JWT_SECRET`; docs: `JWT_SECRET` | Both names supported and documented |
| Compose | Postgres (`db`) only | + Redis, Dockerfiles, `full-preview` profile |

## 3. Phase 4 backlog slices

| Slice ID | Priority | Delivers |
| --- | --- | --- |
| `api-app-module-wiring` | 91 | Wire all modules into production + E2E app |
| `db-migrate-seed-preview` | 92 | Migrate/seed scripts + demo-runbook dataset |
| `config-jwt-env-alignment` | 93 | JWT env parity |
| `web-harness-fixture-gating` | 94 | `VITE_PREVIEW_FIXTURE_MODE`; fail loud by default |
| `compose-full-preview-redis` | 95 | Full Compose topology |
| `e2e-acceptance-suite` | 90 | Re-close after above (live browser + API) |

## 4. Verification

```bash
npm run aih:verify:mvp-integration   # mechanical gate — fails until phase 4 complete
npm run aih:validate:backlog         # backlog includes phase 4 slices
```

## 5. Demo runbook impact

Until phase 4 completes, [`docs/user-manuals/demo-runbook.md`](../user-manuals/demo-runbook.md) may run in **fixture mode** (`VITE_PREVIEW_FIXTURE_MODE=true`) for UI walkthroughs, but that does **not** satisfy release checklist AC-01–AC-19 on production-like data.

After phase 4: runbook flows must work with `VITE_PREVIEW_FIXTURE_MODE=false` against seeded preview DB.

## 6. Related docs

- [10-local-development-setup.md](./10-local-development-setup.md) — migrate/seed commands (target)
- [13-docker-compose-local-runtime.md](./13-docker-compose-local-runtime.md) — full stack topology (target)
- [08-acceptance-mvp-future.md](../brds/08-acceptance-mvp-future.md) — release readiness checklist §4
