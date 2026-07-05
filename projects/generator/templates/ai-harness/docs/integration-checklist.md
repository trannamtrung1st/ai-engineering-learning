# {{PRODUCT_NAME}} — Integration Checklist

Actionable gate checklist for the **`mvp-completion-ready`** finale slice and human release review. Every item must pass before declaring MVP release-ready.

**Related:** [integration-debt-register.md](./integration-debt-register.md) · [../workflows/human-review-checklist.md](../workflows/human-review-checklist.md)

Run mechanical checks first:

```bash
npm run aih:verify:integration
```

---

## 1. API application wiring

- [ ] Root application module (`integration-checks.json` → `appModulePath`) imports all `requiredModules`
- [ ] E2E harness (`e2eHarnessPath`) imports the same module set
- [ ] Integration test asserts key routes register — e.g. protected route returns 401 without token, not 404
- [ ] After change: rebuild API and restart preview

**Do not** mark `mvp-completion-ready` done if modules exist only under `apps/api/src/modules/` but are absent from the root module.

---

## 2. Database migrate and seed

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

## 3. Production admin bootstrap

When privileged roles cannot be created via public signup (see `docs/technical/01-roles-permissions.md` § Account provisioning):

- [ ] `.env.example` documents `INITIAL_ADMIN_EMAIL`, `INITIAL_ADMIN_PASSWORD` (and `INITIAL_ADMIN_ROLE` when multiple admin-class roles)
- [ ] API startup hook creates first admin when admin-class user count is zero (env-gated: `NODE_ENV=production` or `ADMIN_BOOTSTRAP_ENABLED=true`)
- [ ] Root `package.json` exposes `admin:bootstrap` (or name from `integration-checks.json` → `bootstrapAdminNpmScript`)
- [ ] Bootstrap CLI is idempotent — exit 0 with no-op when admin already exists; exit 1 on misconfiguration
- [ ] Bootstrap service never creates demo `*@*.local` users in production
- [ ] Integration test: empty DB + bootstrap env → exactly one admin-class user created
- [ ] Documented in `docs/technical/10-local-development-setup.md` § Production bootstrap

**Verification:**

```bash
npm run aih:verify:integration -- --check bootstrap-admin
npm run admin:bootstrap
```

Skip this section when `integration-checks.json` → `bootstrapAdminNpmScript` is empty (all roles via signup).

---

## 4. Harness fixture gating

- [ ] Shared helper gates fixture mode on `VITE_PREVIEW_FIXTURE_MODE` (or product env var from `integration-checks.json`)
  - Returns `true` only when env flag is explicitly enabled
  - `?fixture=` URL params may still work for browser tester (explicit opt-in per request)
- [ ] API error handlers: if fixtures disabled, **rethrow / set error** — never silent fallback
- [ ] `.env.example`: fixture flag documented with safe default (`false`)
- [ ] With fixtures **disabled** + wired API + seed: pages load from live `/api/v1`, not harness fixtures

**Anti-pattern:** Adding new preview fallbacks without checking the fixture-enablement helper.

---

## 5. Compose full preview

- [ ] `docker-compose.yml` includes services required by `docs/technical/13-docker-compose-local-runtime.md`
- [ ] `apps/api/Dockerfile` and `apps/web/Dockerfile` exist when containerized preview is in scope
- [ ] Compose profiles listed in `integration-checks.json` → `composeProfiles` build and run api + web + db
- [ ] `npm run aih:preview:full` succeeds per [preview-runtime.md](./preview-runtime.md)

---

## 6. HTTP E2E and browser acceptance

Symptoms when broken: `{ "pass": false, "playwrightTestCount": 0, "playwrightSpec": null }`.

- [ ] HTTP E2E harness under `tests/e2e/` covers MVP journeys from `docs/brds/08-acceptance-mvp-future.md`
- [ ] `tests/playwright-ui/scenarios/mvp-completion-ready.spec.ts` exists and lists ≥1 test
- [ ] `ai-harness/playwright-regression-index.json` references the spec for slice `mvp-completion-ready`
- [ ] Browser test agent run produces non-zero `playwrightTestCount` in `{run-id}-browser-test.json`
- [ ] Do not mutate `tests/playwright-ui/test-results/.last-run.json` during implementer screenshots — restore before `SLICE_DONE`
- [ ] Playwright auth uses `ROLE_MATRIX_PASSWORD` consistently — align `tests/playwright-ui/src/support/constants.ts` `DEFAULT_PASSWORD`
- [ ] **Prerequisite:** API wiring + seed complete so browser journeys hit live API where spec expects it

**Verification:**

```bash
npm run aih:preview
npm run aih:browser-test -- mvp-completion-ready
npm run aih:playwright-check -- mvp-completion-ready
```

---

## 7. Release readiness (human + harness)

After `mvp-completion-ready` passes automated gates:

- [ ] `npm run aih:verify:integration` — exit 0
- [ ] `npm run aih:check` full profile — exit 0 including `mvp-completion-ready`
- [ ] Demo runbook executable on **live seeded preview** with fixture mode disabled
- [ ] [human-review-checklist.md](../workflows/human-review-checklist.md) § Live API items checked
- [ ] Acceptance criteria validated against production-like data (not fixture-only)
- [ ] `HUMAN_REVIEW_PASS mvp-completion-ready` recorded
