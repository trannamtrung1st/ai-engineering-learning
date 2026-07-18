# Implementation Notes

## Task 1: Scaffold runnable app with test/lint/build
- Decision: Use the current stable Next.js 16 and React 19 packages with an ESM flat ESLint configuration.
- Why: The repository was greenfield, so there was no compatibility constraint requiring older versions.
- Decision: Let the empty initial Vitest suite pass until domain tests arrive in later tasks.
- Why: Task 1 verifies the test runner wiring before the planned behavioral tests exist.

## Task 2: Schema + demo seed data
- Decision: Use `better-sqlite3` with deterministic seed IDs and reset-before-seed behavior.
- Why: Synchronous local SQLite keeps domain operations and repeatable demo/test setup simple.
- Decision: Seed four users sharing a demo-only scrypt password: one lecturer, two enrolled students, and one non-enrolled student.
- Why: This supports every approved eligibility scenario without adding an import pipeline.

## Task 3: Cookie-session login for Student and Lecturer
- Decision: Use an eight-hour HMAC-signed, httpOnly, same-site cookie containing only user ID, role, and expiry.
- Why: It provides tamper detection and role-aware routing without adding an external auth service to this demo.
- Decision: Accept only local-path `next` redirects after login.
- Why: This preserves the requested return path without creating an open-redirect vulnerability.

## Task 4: Open attendance + rotating multi-use QR tokens
- Decision: Persist only SHA-256 token hashes and retain the currently displayed raw token in process memory.
- Why: Check-in validation does not require storing reusable bearer tokens in plaintext; a process restart safely rotates the display.
- Decision: Rotate lazily when the lecturer UI polls after expiry.
- Why: It guarantees a current 30-second token without adding background jobs to the demo.

## Task 5: Check-in rules
- Decision: Return stable machine-readable rejection reasons and HTTP 422 for valid requests rejected by attendance rules.
- Why: The student UI can show precise outcomes while distinguishing rule failures from malformed or unauthenticated requests.
- Decision: Record the hash of every submitted token, including invalid ones, while never storing the raw bearer token.
- Why: This supports auditability without retaining replayable credentials.

## Task 6: Lecturer manual Present + audit log
- Decision: Restrict manual attendance to students enrolled in the lecturer-owned class section and require a non-blank reason in the domain layer.
- Why: API validation alone is bypassable, and this keeps manual fallback within the approved lecturer scope.
- Decision: Update an existing QR attendance record in place and serialize its before/after values into the audit entry.
- Why: The unique student/session record remains authoritative while preserving the complete correction history.

## Task 7: Minimal demo UI
- Decision: Encode the complete student check-in URL as a real QR image and poll the lecturer endpoint once per second.
- Why: Phones can scan the demo directly, and lazy token rotation becomes visible shortly after each TTL expires.
- Decision: Keep auth gates in server pages while isolating polling and form submission in small client components.
- Why: The protected pages never render to the wrong role, while only interactive code is shipped to the browser.

## Review fixes (2026-07-18)
- Fixed: session secret now fails closed in production if `SESSION_SECRET` is unset.
- Fixed: check-in success write wrapped in a transaction; unique-constraint race now returns `already_checked_in` instead of a 500.
- Fixed: added a lecturer manual-present roster UI (`ManualAttendancePanel` + `getSessionRoster`) so the manual fallback acceptance criterion is reachable in the demo.
- Fixed (nits): removed dead `isAttendanceOpen`, documented the `activeQrTokens` display cache, and reused `sessionCookieOptions` in logout.

## Deferred
- DDL drift: `src/db/seed.ts` hand-writes CREATE TABLE duplicating `src/db/schema.ts`, and the app has no runtime migration step. Reason: acceptable for a seed-driven local demo; proper fix is drizzle-kit migrations, deferred to a future spec. (needs user sign-off)
- Route/auth-boundary tests: 401/403 API guards and page redirects are not directly tested (domain guards are). Reason: thin wrappers over tested domain logic; deferred to a future spec. (needs user sign-off)
