# {{PRODUCT_NAME}} — Integration Checklist

Actionable gate checklist for **phase 4 integration slices** and human release review. Every item must pass before declaring MVP release-ready or re-closing `e2e-acceptance-suite` on live data.

**Related:** [integration-debt-register.md](./integration-debt-register.md) · [../workflows/human-review-checklist.md](../workflows/human-review-checklist.md)

Run mechanical checks first:

```bash
npm run aih:verify:integration
```

---

## 1. API application wiring (`api-app-module-wiring`)

- [ ] Root application module (`integration-checks.json` → `appModulePath`) imports all `requiredModules`
- [ ] E2E harness (`e2eHarnessPath`) imports the same module set
- [ ] Integration test asserts key routes register — e.g. protected route returns 401 without token, not 404
- [ ] After change: rebuild API and restart preview

**Do not** mark slice done if modules exist only under `apps/api/src/modules/` but are absent from the root module.

---

## 2. Database migrate and seed (`db-migrate-seed-preview`)

- [ ] Root `package.json` exposes `db:migrate` and `db:seed`
- [ ] `db:migrate` is idempotent (safe to re-run)
- [ ] `db:seed` creates demo-runbook minimum dataset (documented in `docs/technical/10-local-development-setup.md`)
- [ ] Preview supervisor honors seed enablement env vars when configured

**Verification:**

```bash
npm run aih:dev:db:up
npm run db:migrate && npm run db:seed
npm run aih:preview
curl -sf http://localhost:3001/api/v1/health | jq .
```

---

## 3. Harness fixture gating (`web-harness-fixture-gating`)

- [ ] Shared helper gates fixture mode on `VITE_PREVIEW_FIXTURE_MODE` (or product env var from `integration-checks.json`)
  - Returns `true` only when env flag is explicitly enabled
  - `?fixture=` URL params may still work for browser tester (explicit opt-in per request)
- [ ] API error handlers: if fixtures disabled, **rethrow / set error** — never silent fallback
- [ ] `.env.example`: fixture flag documented with safe default (`false`)
- [ ] With fixtures **disabled** + wired API + seed: pages load from live `/api/v1`, not harness fixtures

**Anti-pattern:** Adding new preview fallbacks without checking the fixture-enablement helper.

---

## 4. Compose full preview (`compose-full-preview`)

- [ ] `docker-compose.yml` includes services required by `docs/technical/13-docker-compose-local-runtime.md`
- [ ] `apps/api/Dockerfile` and `apps/web/Dockerfile` exist when containerized preview is in scope
- [ ] Compose profiles listed in `integration-checks.json` → `composeProfiles` build and run api + web + db
- [ ] `npm run aih:preview:full` succeeds per [preview-runtime.md](./preview-runtime.md)

---

## 5. Browser gate (`e2e-acceptance-suite`)

Symptoms when broken: `{ "pass": false, "playwrightTestCount": 0, "playwrightSpec": null }`.

- [ ] `tests/playwright-ui/scenarios/e2e-acceptance-suite.spec.ts` exists and lists ≥1 test
- [ ] `ai-harness/playwright-regression-index.json` references the spec for slice `e2e-acceptance-suite`
- [ ] Browser test agent run produces non-zero `playwrightTestCount` in `{run-id}-browser-test.json`
- [ ] Do not mutate `tests/playwright-ui/test-results/.last-run.json` during implementer screenshots — restore before `SLICE_DONE`
- [ ] Playwright auth uses `ROLE_MATRIX_PASSWORD` consistently — align `tests/playwright-ui/src/support/constants.ts` `DEFAULT_PASSWORD`
- [ ] **Prerequisite:** phase 4 integration complete (API wiring + seed) so browser journeys hit live API where spec expects it

**Verification:**

```bash
npm run aih:preview
npm run aih:browser-test -- e2e-acceptance-suite
npm run aih:playwright-check -- e2e-acceptance-suite
```

---

## 6. Release readiness (human + harness)

After all phase 4 slices pass:

- [ ] `npm run aih:verify:integration` — exit 0
- [ ] `npm run aih:check` full profile — exit 0 including `e2e-acceptance-suite`
- [ ] Demo runbook executable on **live seeded preview** with fixture mode disabled
- [ ] [human-review-checklist.md](../workflows/human-review-checklist.md) § Live API items checked
- [ ] Acceptance criteria validated against production-like data (not fixture-only)
