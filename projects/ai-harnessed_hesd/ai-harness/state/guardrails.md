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
- [module-notification] AC-25 in slice acceptance was doc drift (manual-fallback operability) — notification slice owns FR-26/BR-17 only; remove AC-25 from acceptanceTags when TestGen maps manual-fallback cases
- [web-design-system-shell] Browser test failed — see 20260702T160633Z-browser-test.json
- [web-design-system-shell] Scope gate failed — out-of-scope files: apps/web/src/test/setup.ts
apps/web/vitest.config.ts
tests/playwright-ui/scenarios/web-design-system-shell.spec.ts
- [web-design-system-shell] Browser test failed — see 20260702T163452Z-browser-test.json
- [web-student-check-in-flow] Browser test failed — see 20260702T172530Z-browser-test.json
- [web-student-attendance-history] Browser test failed — see 20260702T175527Z-browser-test.json
- [web-student-attendance-history] Listing status filter `<option>` labels must not duplicate AttendanceStatusCell badge copy — Playwright `getByText('Có mặt').first()` matches hidden `<option>` before visible badge when labels collide
- [web-lecturer-session-control] Browser test failed — see 20260702T182222Z-browser-test.json
- [web-lecturer-session-control] Do not hide `SessionControlBar` at `max-height: 720px` — Playwright lecturer viewport is 1280×720; hiding the bar breaks TC-FR-07-012/TC-FR-14-011/TC-AC-01-008 (Open CTA, room/time context, openedAt metadata)
- [web-lecturer-session-control] Computational checks failed — see 20260702T184717Z-checks.json
- [web-academic-admin-academic-setup] Browser test failed — see 20260702T192214Z-browser-test.json
- [web-academic-admin-academic-setup] PG-04 FR-06 requires `Sĩ số` (enrolledCount) column from GET /class-sessions — preview seed sessions must stay Scheduled via `db:seed` refresh when browser gate retries TC-FR-06-012 in isolation
- [web-academic-admin-policy-management] AI review failed — see 20260702T200305Z-review.json
- [web-academic-admin-policy-management] PolicyForm must reset scopeId when scopeType changes (useEffect + scopeIdMatchesType validation) — Faculty policy cannot submit with ClassSection scopeId (FR-24)
- [web-academic-admin-policy-management] PG-12 sort toggle must update local sortOrder state immediately; only one active ClassSection policy per section — bootstrap SE101-02 + second policy for TC-FR-24-014 sort assertion
- [web-academic-admin-policy-management] Browser test failed — see 20260702T201809Z-browser-test.json
- [web-academic-admin-policy-management] PG-12 filter chip remove aria-label must use `Gỡ …` not `Xóa bộ lọc …` — collides with TableToolbar clear-all in Playwright strict mode (TC-FR-24-014)
- [web-academic-admin-policy-management] AC-10 roster distance metadata requires attendance-ledger + AttemptOutcomeCell paths in slice completionArtifacts when extending GET /attendance rows
- [web-system-auditor-audit-review] SystemAuditor GET /audit-logs list requires `createAuthorizeGuard` resolveScope to pass actor Faculty/ClassSection scope — empty scopeContext yields OutOfScope before M08 query runs
- [web-system-auditor-audit-review] Preview seed SystemAuditor uses Faculty scope (not Institution) until M08 collectScopedSectionIds treats Institution-wide auditor; use `system-auditor@attendly.local` email to avoid identity.integration.test `auditor@attendly.local` collision
- [web-system-auditor-audit-review] Browser test failed — see 20260702T213529Z-browser-test.json
- [web-system-auditor-audit-review] AuditorSessionRosterPage must not call GET /class-sessions/{id} (SessionControl:execute) — SystemAuditor has AttendanceRecord:read only; render LiveRosterPanel directly via GET /class-sessions/{id}/attendance
- [test-backend-integration-critical-path] Critical-path integration fixtures must use dedicated section hierarchy with explicit gps-off Course/ClassSection policies and Self-scoped Student role for unenrolled actor — shared seed course policies and ClassSection-only student roles cause GpsRequired/403 flakes
