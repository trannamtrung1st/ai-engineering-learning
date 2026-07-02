# Attendly — Harness Requirements Index

One-page map from harness agents to product docs. Full specs live under `docs/` — this index avoids loading the entire tree. **Customize** row notes per product during harness-context-maps or as docs evolve.

## BRD set (`docs/brds/`)

| File | Contents | Tags |
| --- | --- | --- |
| [prompt.md](../../docs/brds/prompt.md) | MVP scope summary | — |
| [00-project-overview.md](../../docs/brds/00-project-overview.md) | Vision, metrics | — |
| [01-stakeholders-scope.md](../../docs/brds/01-stakeholders-scope.md) | Roles, in/out scope | — |
| [02-business-workflow.md](../../docs/brds/02-business-workflow.md) | End-to-end flows | — |
| [03-functional-requirements.md](../../docs/brds/03-functional-requirements.md) | Functional requirements | FR-* |
| [04-business-rules.md](../../docs/brds/04-business-rules.md) | Business rules | BR-* |
| [05-state-machine.md](../../docs/brds/05-state-machine.md) | State machines | — |
| [06-domain-model.md](../../docs/brds/06-domain-model.md) | Entities | — |
| [07-non-functional-risk.md](../../docs/brds/07-non-functional-risk.md) | Non-functional requirements | NFR-* |
| [08-acceptance-mvp-future.md](../../docs/brds/08-acceptance-mvp-future.md) | Acceptance criteria | AC-* |

TestGen resolves doc lists per tag via [`config/testgen-docs-map.json`](../config/testgen-docs-map.json).

## UI/UX (`docs/ui-ux/`)

| File | Use when |
| --- | --- |
| [00-production-ui-quality-bar.md](../../docs/ui-ux/00-production-ui-quality-bar.md) | Every frontend slice — merge gate |
| [DESIGN.md](../../docs/ui-ux/DESIGN.md) | Authoritative design spec |
| [01-design-overview.md](../../docs/ui-ux/01-design-overview.md) | Visual direction |
| [01-ui-ux-foundation.md](../../docs/ui-ux/01-ui-ux-foundation.md) | Copy, states, personas |
| [03-design-system-basics.md](../../docs/ui-ux/03-design-system-basics.md) | System layers, principles |
| [04-design-tokens.md](../../docs/ui-ux/04-design-tokens.md) | CSS mapping (DESIGN.md → variables) |
| [05-common-ui-components.md](../../docs/ui-ux/05-common-ui-components.md) | Primitives, `TableToolbar` |
| [06-app-layout-components.md](../../docs/ui-ux/06-app-layout-components.md) | Shells, nav |
| [14-listing-pages-search-filter-sort.md](../../docs/ui-ux/14-listing-pages-search-filter-sort.md) | Listing §0 matrix (when applicable) |

## Technical (`docs/technical/`)

| File | Use when |
| --- | --- |
| [01-roles-permissions.md](../../docs/technical/01-roles-permissions.md) | RBAC, nav permissions |
| [05-api-design.md](../../docs/technical/05-api-design.md) | HTTP contracts |
| [07-state-machines.md](../../docs/technical/07-state-machines.md) | Concurrency, locking, lifecycle |
| [08-validation-rules.md](../../docs/technical/08-validation-rules.md) | Error codes, validation |
| [11-testing-plan.md](../../docs/technical/11-testing-plan.md) | Test pyramid, TestGen, flake triage |
| [13-docker-compose-local-runtime.md](../../docs/technical/13-docker-compose-local-runtime.md) | Persistence policy, test stack |

## Harness skills

| Skill | Role |
| --- | --- |
| [visual-design](../skills/visual-design/SKILL.md) | Design-system craft, style profile, screenshot review |
| [ui-ux-testing](../skills/ui-ux-testing/SKILL.md) | Browser tester UX audit taxonomy |

**Precedence:** [DESIGN.md](../../docs/ui-ux/DESIGN.md) > [04-design-tokens.md](../../docs/ui-ux/04-design-tokens.md) > [01-design-overview.md](../../docs/ui-ux/01-design-overview.md) > craft skills.

## Harness capability docs

| Doc | Role |
| --- | --- |
| [browser-mcp.md](./browser-mcp.md) | Playwright MCP runbook |
| [playwright-regression.md](./playwright-regression.md) | Committed UI spec codegen |
| [test-failure-triage.md](./test-failure-triage.md) | Integration/e2e flake triage, `SLICE_DEFER` policy |
| [ux-bug-logging.md](./ux-bug-logging.md) | `UX-*` bug schema and gate |
| [ui-visual-verification.md](./ui-visual-verification.md) | Implementer screenshot checklist |
