# Generator guardrails

Verification failures and remediation notes for generator agents.

## Signs

- **Backport generic harness improvements:** When a live harnessed project (e.g. `ai-harnessed_attendly`) discovers reusable harness infrastructure — scripts, gate policy, triage machinery, agent prompt rules — backport to `templates/ai-harness/`. Do not leave improvements only in the live repo; future `GEN_APPLY=1` scaffolds must inherit them.
- **Integration test flakes:** Classify with isolated vitest + `{run-id}-integration-triage.json`. Prohibit bare full-suite re-run as resolution. Owner slice must fix parallel test isolation (afterEach restore, dedicated section/session fixtures).
- **Template placeholders:** When porting from a live project, replace product names and workspaces with `{{PRODUCT_NAME}}`, `{{WORKSPACE_NAME}}`, `{{PRODUCT_SLUG}}`, `{{BRANCH_PREFIX}}` — never copy product-specific literals (e.g. `@attendly/*`) into `templates/ai-harness/`.
