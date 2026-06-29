# Harness guardrails

Verification failures and remediation notes for harness agents.
- [AC-04] Test case validation failed — see 20260628T172128Z-testgen.txt
- [AC-13] Test case validation failed — see 20260628T173849Z-testgen.txt
- [AC-13] Test case validation failed — see 20260628T174010Z-testgen.txt
- [NFR-01] Test case validation failed — see 20260628T183306Z-testgen.txt
- [NFR-07] Test case validation failed — see 20260628T184242Z-testgen.txt
- [NFR-11] Test case validation failed — see 20260628T184941Z-testgen.txt
- [NFR-15] Test case validation failed — see 20260628T185520Z-testgen.txt
- [NFR-16] Test case validation failed — see 20260628T185943Z-testgen.txt
- [NFR-17] Test case validation failed — see 20260628T190253Z-testgen.txt
- [NFR-20] Test case validation failed — see 20260628T191006Z-testgen.txt
- [domain-package] Computational checks failed — see 20260628T192740Z-checks.json
- [api-foundation] Computational checks failed — see 20260628T193455Z-checks.json
- [module-session-management] Computational checks failed — see 20260628T200826Z-checks.json
- [module-attendance] Computational checks failed — see 20260628T203417Z-checks.json
- [module-checkin-qr] Computational checks failed — see 20260628T205057Z-checks.json
- [module-reporting-export] Computational checks failed — see 20260628T210529Z-checks.json
- [module-reporting-export] AI review failed — see 20260628T211228Z-review.json
- [web-design-system-shell] Browser test failed — see 20260628T212831Z-browser-test.json
- [web-design-system-shell] Browser test failed — see 20260628T213809Z-browser-test.json

## Signs

- **Sonner toast + React StrictMode:** Do not guard session-expired (or bootstrap) toasts with a `useRef` "shown once" flag. StrictMode remounts `<Toaster />` and drops the first toast; the ref blocks the second `toast.error` call. Use `toast.error(..., { id })` and defer with `setTimeout(0)` in `useEffect` so the toast fires after the remount.
- **Preview seed idempotency:** Do not gate `runPreviewSeed` on a policy_settings marker alone — integration tests truncate auth tables but can leave `preview_seed_version` set, causing browser gates to skip seed and miss deactivated/student fixtures. Verify fixture rows (e.g. `deactivated@example.edu.vn`) exist before skipping.
- [web-design-system-shell] Browser test failed — see 20260628T215822Z-browser-test.json
- [web-student-checkin] Browser test failed — see 20260628T224030Z-browser-test.json
- **Preview seed token fixtures:** Do not tie `isSeedApplied` to QR token rows — re-running full seed calls `sessionService.open` on already-Active sessions and crashes API in a restart loop. Upsert browser-gate tokens via `ensurePreviewTokenFixtures()` on every startup instead.
- **QR scheduler vs preview fixtures:** `QrScheduler.rotate` mass-expires all Valid tokens for a session — protect fixed browser-gate token IDs via `setProtectedTokenIds` and refresh fixture `issued_at` on preview refresh so deep-link tokens stay valid. **`getCurrentToken` must exclude protected fixture IDs** so instructor QR display rotates on the 30 s scheduler cadence (NFR-06); never let fixture refresh become the displayed token.
- [web-student-checkin] Computational checks failed — see 20260628T225621Z-checks.json
- [web-student-checkin] Computational checks failed — see 20260628T230948Z-checks.json
- [web-student-checkin] Browser test failed — see 20260628T231616Z-browser-test.json
- **Preview seed monitor vs NotEnrolled:** Keep `studentB` unenrolled for NotEnrolled browser gates; use `studentC` (enrolled Pending, attendance reset on fixture refresh) for OutOfRadius/spoof monitor fixtures — never enroll studentB in `ensurePreviewMonitorFixtures`.
- **pg_advisory_lock + pg Pool:** Never `pg_advisory_lock` across pooled `db.query()` calls — lock/unlock may run on different connections and hang integration tests until DB restart.
- **Preview seed vs integration tests:** When preview stack runs during `aih:check`, skip `@wecheck/api` build (like web) so `node --watch` does not restart API and re-run full `runPreviewSeed` mid-suite; use `ensurePreviewDeactivatedUser` on refresh instead of `ensurePreviewUserFixtures` in the early-return path.
- [web-student-checkin] Browser test failed — see 20260628T234708Z-browser-test.json
- [web-student-checkin] Computational checks failed — see 20260629T000645Z-checks.json
- [web-student-checkin] Computational checks failed — see 20260629T013605Z-checks.json
- [web-design-system-shell] Browser test failed — see 20260629T035100Z-browser-test.json
- [web-design-system-shell] Browser test failed — see 20260629T043148Z-browser-test.json
- **Role layout Outlet context:** Nested `StudentLayout` / `InstructorLayout` / `AdminLayout` must pass `<Outlet context={authContext} />` — page components using `useAuthUser()` (e.g. `/admin/export` RBAC) crash without forwarded `RequireAuth` context.
- **Preview seed vs integration truncate:** `truncateAuthTables` must truncate sessions/QR/attendance before `DELETE FROM users` when preview stack runs — preview fixture `class_assignments` and `sessions` rows otherwise race integration resets.
- **Integration test fixture IDs:** Never use preview `PREVIEW_INSTITUTIONAL_IDS` values (`ADMIN001`, `SV2026001`, etc.) in integration tests — `clearPreviewUserConflicts` during concurrent preview re-seed deletes them and breaks duplicate/RBAC assertions.
- [web-design-system-shell] Computational checks failed — see 20260629T045336Z-checks.json
- [web-student-checkin] Browser test failed — see 20260629T054958Z-browser-test.json
- **QR deep link alias parsing:** `parseCheckInQrPayload` must resolve preview aliases (`valid-token-id`, `sess-1`) — strict UUID-only parsing breaks manual QR paste and TC-FR-07-013 browser gates (GpsDisabled instead of API submit).
- [web-student-checkin] Browser test failed — see 20260629T060953Z-browser-test.json
- [web-student-checkin] Computational checks failed — see 20260629T064007Z-checks.json
- **cameraSim scanner consent:** When `cameraSim=deny|grant` forces scanner entry via `readForceScannerEntry()`, treat camera as consented for `QrScannerView` (`scannerCameraConsented`) — otherwise sim denial never runs and browser gates see the consent banner instead of `camera_denied` + PermissionGuideModal (TC-NFR-19-016).
- [web-student-checkin] Browser test failed — see 20260629T065246Z-browser-test.json
- **BR-12 submit gating:** Separate GPS capture from API submit on deep-link auto-flow — always render `Xác nhận điểm danh` on GPS step (disabled + `gps-required-badge` until coords ready); never auto-submit after capture (TC-BR-12-014).
- [web-student-checkin] Computational checks failed — see 20260629T075110Z-checks.json
- **Unit test deferred GPS mock:** When testing TC-BR-12-014 submit gating, create the deferred `Promise` before `renderFlow` and `await waitFor(() => expect(captureGeolocation).toHaveBeenCalled())` before resolving — assigning `resolveGeo` inside `mockImplementation` races React `useEffect`.
- [web-student-checkin] Browser test failed — see 20260629T075909Z-browser-test.json
- **TC-NFR-18-013 physical device matrix:** Cases with `harnessSkip: physical-device` in test artifacts (TC-NFR-18-013, TC-NFR-19-013/014) must be reported `SKIP — physical-device`, never `FAIL`, in Playwright MCP gates. Pre-pilot emulation evidence: `ai-harness/generated/runs/pilot-device-matrix-nfr-18.json`.
- [web-instructor-sessions] Browser test failed — see 20260629T092108Z-browser-test.json
