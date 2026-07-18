# Progress: Attendance status and policy

- [x] Task 1: Schema + seeded section policy — verify: `npx tsx src/db/seed.ts && npx vitest run src/db/seed.test.ts` -> PASS
- [x] Task 2: Check-in Present / Late / outside-window rejection — verify: `npx vitest run src/domain/check-in.test.ts` -> PASS
- [x] Task 3: Close attendance → auto-mark Absent — verify: `npx vitest run src/domain/close-attendance.test.ts` -> PASS
- [x] Task 4: Lecturer manual statuses + audit — verify: `npx vitest run src/domain/manual-attendance.test.ts` -> PASS
- [x] Task 5: Lecturer UI — Close + status picker — verify: `npm test && npm run lint && npm run build` -> PASS

## Verify (2026-07-18)
- tests: PASS
- lint: PASS
- build: PASS
- overall: PASS

## Review (2026-07-18)
- blockers: 0 found, 0 open
- should-fix: 3 found, 3 fixed (student UI showed "Present" during Late window; auto-absent now uses a distinct `system` method; app self-initializes + non-destructively migrates pre-existing DBs) — user chose to fix all
- nits: 7 found, 3 fixed (missing outside-window message, redundant seed DELETE, added exact-boundary tests), 4 ignored (window/enrollment check order, close-state guard, component/route test suite, close-idempotency test)
- re-verified after fixes: tests 36 PASS, lint PASS, build PASS, attestation VALID

## Verify (2026-07-18, full re-run post-review)
- tests: PASS (36 tests, 7 files)
- lint: PASS
- build: PASS
- overall: PASS — attestation VALID
