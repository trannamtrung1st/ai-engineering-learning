# Harness guardrails

Verification failures and remediation notes for harness agents.

## Doc requirements

- **Listing pages:** Collection views must implement search, filter, sort, and pagination per [14-listing-pages-search-filter-sort.md](../docs/ui-ux/14-listing-pages-search-filter-sort.md) §0 (documented UX variants allowed). Apply `TableToolbar` and listing chrome per [design-system/tables.md](../../docs/ui-ux/design-system/tables.md).
- **Design craft:** Visual implementation via [`visual-design`](../skills/visual-design/SKILL.md) and [design-system/](../../docs/ui-ux/design-system/) modules. Authoritative index [DESIGN.md](../../docs/ui-ux/DESIGN.md); product tokens in [04-design-tokens.md](../../docs/ui-ux/04-design-tokens.md) always win for CSS values.
- **Table toolbar:** Listing routes use `TableToolbar` per [05-common-ui-components.md](../../docs/ui-ux/05-common-ui-components.md).

## Signs

- [AC-06] Test case validation failed — see 20260702T094600Z-testgen.txt
- [AC-13] Test case validation failed — see 20260702T100156Z-testgen.txt
- [AC-20] Test case validation failed — see 20260702T101958Z-testgen.txt
- [module-attendance-ledger] SLICE_BLOCKED scope gate has unrelated out-of-scope apps/api/src/infra/compose-config.test.ts change and test:e2e targets missing @attendly/e2e workspace
- [infra-local-runtime-compose] apps/api/src/infra/compose-config.test.ts still asserts hesd_test while docker-compose.test.yml uses attendly_test — fails test:unit for every backend slice until infra slice is fixed
- [module-attendance-ledger] Deferred to slice infra-local-runtime-compose: compose-config.test.ts stale hesd_test assertion blocks test:unit for all backend slices; M05 implementation and integration tests are complete
