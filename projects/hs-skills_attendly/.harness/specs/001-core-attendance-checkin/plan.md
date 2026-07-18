# Plan: Core attendance check-in

**Status:** approved

**Baseline:** `node -e "…greenfield…"` -> PASS (no app suite existed yet; see `.harness/specs/001-core-attendance-checkin/state/baseline.status`)

**Approach (how):** Next.js App Router + TypeScript, SQLite via Drizzle, cookie sessions, Vitest for domain/API tests. Mobile-web student check-in and lecturer QR UI share one app. No GPS, import, export, or extra roles.

## Task 1: Scaffold runnable app with test/lint/build
- Spec: prerequisite so later acceptance criteria can be verified mechanically
- Files: `package.json`, `tsconfig.json`, `next.config.ts`, `vitest.config.ts`, `eslint.config.*`, `src/app/layout.tsx`, `src/app/page.tsx`
- Do:
  - Create Next.js (App Router) + TypeScript project with Vitest and ESLint
  - Add npm scripts: `test`, `lint`, `build`
- Verify: `npm test && npm run lint && npm run build`

## Task 2: Schema + demo seed data
- Spec: WHEN the product is started for demo THEN seed data provides lecturer, class section, enrollments, and a class session
- Files: `src/db/schema.ts`, `src/db/client.ts`, `src/db/seed.ts`, `drizzle.config.ts` (or equivalent)
- Do:
  - Model User (role student|lecturer), ClassSection, Enrollment, ClassSession, QrSessionToken, CheckInAttempt, AttendanceRecord, AuditLog
  - Seed ≥1 lecturer, ≥2 enrolled students, ≥1 non-enrolled student, 1 section, 1 session
- Verify: `npx tsx src/db/seed.ts && npx vitest run src/db/seed.test.ts`

## Task 3: Cookie-session login for Student and Lecturer
- Spec: WHEN a student is not logged in and opens the check-in flow THEN they are redirected to login before attendance can be recorded
- Files: `src/auth/session.ts`, `src/app/login/page.tsx`, `src/app/api/auth/login/route.ts`, `src/app/api/auth/logout/route.ts`, `src/auth/session.test.ts`
- Do:
  - Implement login against seeded credentials; issue httpOnly session cookie with user id + role
  - Protect check-in API/pages so unauthenticated callers get login redirect or 401
- Verify: `npx vitest run src/auth/session.test.ts`

## Task 4: Open attendance + rotating multi-use QR tokens
- Spec: lecturer opens owned session → short-lived multi-use QR (~30s TTL) refreshes while open; same valid token usable by multiple students
- Files: `src/domain/qr-session.ts`, `src/domain/qr-session.test.ts`, `src/app/api/sessions/[id]/open/route.ts`, `src/app/api/sessions/[id]/qr/route.ts`
- Do:
  - Open attendance only for the owning lecturer; mint rotating tokens bound to the session
  - Expose current token for display; expire old tokens after TTL
- Verify: `npx vitest run src/domain/qr-session.test.ts`

## Task 5: Check-in rules (success + all rejection paths)
- Spec: enrolled logged-in student → Present (method QR); reject expired/wrong/closed, non-enrolled, and duplicate success; record failed attempts with reasons
- Files: `src/domain/check-in.ts`, `src/domain/check-in.test.ts`, `src/app/api/check-in/route.ts`
- Do:
  - Implement validation order matching the spec (open session, token, enrollment, not already present)
  - Persist AttendanceRecord on success and CheckInAttempt on every try (success or fail)
- Verify: `npx vitest run src/domain/check-in.test.ts`

## Task 6: Lecturer manual Present + audit log
- Spec: owning lecturer can set Manual Present; audit records actor, time, old/new, reason
- Files: `src/domain/manual-attendance.ts`, `src/domain/manual-attendance.test.ts`, `src/app/api/sessions/[id]/manual/route.ts`
- Do:
  - Allow owning lecturer to set/update attendance to Manual Present with a required reason
  - Write AuditLog entry with before/after values
- Verify: `npx vitest run src/domain/manual-attendance.test.ts`

## Task 7: Minimal demo UI (lecturer QR + student check-in)
- Spec: demo path from seed alone; lecturer sees rotating QR; student can complete check-in or see clear rejection
- Files: `src/app/lecturer/sessions/[id]/page.tsx`, `src/app/check-in/page.tsx`, `src/components/QrDisplay.tsx`
- Do:
  - Lecturer page: open attendance + display current QR (poll/refresh on TTL)
  - Student page: require login, submit token, show success or rejection message
- Verify: `npm test && npm run lint && npm run build`
