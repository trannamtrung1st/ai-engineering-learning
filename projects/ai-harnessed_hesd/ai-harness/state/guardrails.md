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
- [module-attendance-ledger] AI review failed — see 20260702T142648Z-review.json
- [module-policy-engine] Computational checks failed — see 20260702T144500Z-checks.json
- [module-policy-engine] AI review failed — see 20260702T145558Z-review.json
- [module-policy-engine] Policy-engine integration tests must use dedicated faculty/course/section hierarchy (not shared seed section) — course/faculty scoped policies pollute parallel M04 check-in tests on the same course
- [module-reporting-and-export] Computational checks failed — see 20260702T150919Z-checks.json
- [module-audit-and-compliance] M07 reporting integration `deleteExportJobsForActor(lecturer|academicAdmin)` wipes all ExportJob audit rows for that actor — parallel audit export query tests must use an ephemeral actor user, not seed lecturer
- [module-realtime-delivery] Computational checks failed — see 20260702T153930Z-checks.json
- [module-realtime-delivery] M09 integration fixtures must use dedicated faculty/term/course hierarchy (not shared seed term) — parallel runs pollute M07 reporting scope queries for SEED.term
