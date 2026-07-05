# Human Review Checklist

Complete before merging a `mergeReady` slice or closing an `aih/*` branch.

## Slice verification

- [ ] Slice id and acceptance tags (`AC-*`, `BR-*`) are satisfied
- [ ] `ai-harness/whole-app-backlog.json` shows `passes: true` for this slice only after automated gates
- [ ] No scope creep beyond `docs/brds/08-acceptance-mvp-future.md`

## Persistence and runtime

- [ ] Postgres via Docker Compose — no in-memory repos, SQLite, or page mock stores
- [ ] `DATABASE_URL` targets Compose Postgres in dev
- [ ] Migrations run against Postgres before API startup
- [ ] **`npm run aih:verify:integration` passes**
- [ ] Preview demo works with `VITE_PREVIEW_FIXTURE_MODE=false` on seeded DB

## MVP completion (`mvp-completion-ready` — required before MVP merge)

- [ ] All modules in root application module; feature `/api/v1` routes not 404
- [ ] Demo accounts and minimum dataset seeded (`db:migrate` + `db:seed`)
- [ ] No silent fixture fallback in default preview
- [ ] HTTP E2E harness passes on live preview data
- [ ] Browser acceptance gate passes (`tests/playwright-ui/scenarios/mvp-completion-ready.spec.ts`)
- [ ] See [integration-checklist.md](../docs/integration-checklist.md)

## Business rules

- [ ] Canonical states match `docs/technical/07-state-machines.md`
- [ ] Validation error codes match `docs/technical/08-validation-rules.md`
- [ ] Idempotency and concurrency rules enforced per `docs/technical/08-validation-rules.md`
- [ ] Critical config changes are audit-logged

## Frontend (if applicable)

- [ ] Meets `docs/ui-ux/00-production-ui-quality-bar.md`
- [ ] Implementer screenshots spot-checked for button contrast and padding per `ai-harness/docs/ui-visual-verification.md`
- [ ] `tests/playwright-ui/scenarios/<slice-id>.spec.ts` exists for frontend slices
- [ ] No open P0/P1 `UX-*` bugs in latest browser test report
- [ ] Live `/api/v1` data — no hardcoded fixtures **unless** `VITE_PREVIEW_FIXTURE_MODE=true` is explicitly documented for the review build
- [ ] AppShell, tokens, loading/empty/error states present
- [ ] Signed-in TopBar shows user display name (or email fallback), not internal actor/user ID

## Local smoke

- [ ] `npm run aih:preview:verify` passes (or `npm run aih:preview:full` + verify for merge-ready infra slices)
- [ ] API health: `status=ok`, `db=connected` at `http://localhost:3001/api/v1/health`
- [ ] Web responds HTTP 200 at `http://localhost:3007/` (preview stack default)
- [ ] One end-to-end path exercised manually per slice scope

## Sign-off

When all items pass, record:

```
HUMAN_REVIEW_PASS mvp-completion-ready
```
