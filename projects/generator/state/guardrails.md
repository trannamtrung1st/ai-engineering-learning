# Generator guardrails

Verification failures and remediation notes for generator agents.

## Signs

- **Backport generic harness improvements:** When a live harnessed project (e.g. `ai-harnessed_attendly`) discovers reusable harness infrastructure — scripts, gate policy, triage machinery, agent prompt rules — backport to `templates/ai-harness/`. Do not leave improvements only in the live repo; future `GEN_APPLY=1` scaffolds must inherit them.
- **Integration test flakes:** Classify with isolated `node --test` + `{run-id}-integration-triage.json`. Prohibit bare full-suite re-run as resolution. Owner slice must fix parallel test isolation (afterEach restore, dedicated section/session fixtures).
- **Template placeholders:** When porting from a live project, replace product names and workspaces with `{{PRODUCT_NAME}}`, `{{WORKSPACE_NAME}}`, `{{PRODUCT_SLUG}}`, `{{BRANCH_PREFIX}}` — never copy product-specific literals (e.g. `@attendly/*`) into `templates/ai-harness/`.
- **Integration gate naming:** Use generic `verify-integration.sh` + `aih:verify:integration` in templates — not product-prefixed `verify-mvp-integration` / `mvp-integration-*` doc names.

## Harness backport classification

| Class | Examples | Action |
| --- | --- | --- |
| **PORT** | `scripts/run-checks.sh`, `workflows/ralph-loop.json`, `schemas/*.schema.json`, generic agent prompt rules | Copy to `templates/ai-harness/`; run `npm run gen:self-check` |
| **PLACEHOLDER** | Agent prompts with product name, `browser-mcp.md` actor sections, `preview-runtime.md` workspace refs | Generalize literals → `{{PRODUCT_NAME}}`, `{{WORKSPACE_NAME}}`, `{{PRIMARY_ACTOR}}` before porting |
| **SKIP** | `whole-app-backlog.json`, `test-case-index.json`, `config/plan-index.json`, `plans/<slice-id>.md` (Ralph runtime), `plans/whole-app-backlog.md` (generator step output — do not backport from live repos), `context-map.json` (generated), `playwright-regression-index.json` runtime entries, `state/progress.md` | Do not copy — harness-planner or Ralph loop owns these |
| **GENERICIZE** | Live `mvp-integration-*` docs/scripts | Port as `integration-debt-register.md`, `integration-checklist.md`, `verify-integration.sh` + `config/integration-checks.json` |

Run `./scripts/backport-harness-diff.sh` after live-project harness work to list remaining PORT deltas.

