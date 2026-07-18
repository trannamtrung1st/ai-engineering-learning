# Progress

- [x] Task 1: Scaffold runnable app with test/lint/build — verify: `npm test && npm run lint && npm run build` -> PASS
- [x] Task 2: Schema + demo seed data — verify: `npx tsx src/db/seed.ts && npx vitest run src/db/seed.test.ts` -> PASS
- [x] Task 3: Cookie-session login for Student and Lecturer — verify: `npx vitest run src/auth/session.test.ts` -> PASS
- [x] Task 4: Open attendance + rotating multi-use QR tokens — verify: `npx vitest run src/domain/qr-session.test.ts` -> PASS
- [x] Task 5: Check-in rules (success + all rejection paths) — verify: `npx vitest run src/domain/check-in.test.ts` -> PASS
- [x] Task 6: Lecturer manual Present + audit log — verify: `npx vitest run src/domain/manual-attendance.test.ts` -> PASS
- [x] Task 7: Minimal demo UI (lecturer QR + student check-in) — verify: `npm test && npm run lint && npm run build` -> PASS

## Verify (2026-07-18)
- tests: PASS (18 tests, 5 files)
- lint: PASS
- build: PASS
- overall: PASS (attestation VALID)

## Review (2026-07-18)
- blockers: 0 found, 0 open
- should-fix: 5 found, 3 fixed (secret guard, check-in transaction/race, manual-present UI), 2 deferred (DDL drift, route/auth tests — see implement-notes.md, pending sign-off)
- nits: 5 found, 3 fixed (dead code, cache comment, logout cookie), 2 ignored (poll cadence, token-in-URL)
- re-verified after fixes: tests 19 PASS, lint PASS, build PASS, attestation VALID
