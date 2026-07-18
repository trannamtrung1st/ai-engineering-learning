# Progress: Attendance reporting

- [x] Task 1: Make audit logs record-optional — verify: `node scripts/run-check.mjs task-1 -- npm test` -> PASS
- [x] Task 2: Seed mixed attendance history — verify: `node scripts/run-check.mjs task-2 -- npm test` -> PASS
- [x] Task 3: Student history domain query — verify: `node scripts/run-check.mjs task-3 -- npm test` -> PASS
- [x] Task 4: Section report domain query — verify: `node scripts/run-check.mjs task-4 -- npm test` -> PASS
- [x] Task 5: CSV export with audit — verify: `node scripts/run-check.mjs task-5 -- npm test` -> PASS
- [x] Task 6: Student history page — verify: `node scripts/run-check.mjs task-6 -- npm run lint && node scripts/run-check.mjs task-6-build -- npm run build` -> PASS
- [x] Task 7: Lecturer report page — verify: `node scripts/run-check.mjs task-7 -- npm run lint && node scripts/run-check.mjs task-7-build -- npm run build` -> PASS

## Verify (2026-07-18)
- tests: PASS (46 tests, 8 files)
- lint: PASS
- build: PASS
- overall: PASS (attested)

## Verify (2026-07-18, re-run)
- tests: PASS (46 tests, 8 files)
- lint: PASS
- build: PASS
- overall: PASS (attestation VALID)

## Review (2026-07-18)
- blockers: 0 found, 0 open
- should-fix: 3 found, 2 fixed (CSV formula injection; audit-write-on-GET → export route now POST + form-based download, per user sign-off), 1 downgraded to nit (hardcoded demo redirect mirrors existing check-in convention)
- nits: 4 found, 2 fixed (CSV row/null-rate test coverage), 2 ignored (audit not in transaction, Content-Disposition interpolation)
- re-verified after fixes: tests 49 PASS, lint PASS, build PASS, attestation VALID
