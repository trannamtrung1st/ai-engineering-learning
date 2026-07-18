## Task 1: Schema + seeded section policy
- Decision: Seed a 10-minute present window followed by a 20-minute late window.
- Why: Both are non-zero, easy to exercise in a demo, and keep the distinction visible without an unusually long wait.
- Decision: Rebuild the demo database tables before seeding.
- Why: The seed already deletes all demo data, and rebuilding ensures existing SQLite files receive new columns and CHECK constraints that `CREATE TABLE IF NOT EXISTS` cannot apply.

## Task 2: Check-in Present / Late / outside-window rejection
- Decision: Treat the exact present-window endpoint as Present and the exact late-window endpoint as Late.
- Why: Each configured duration remains fully inclusive, and rejection begins only after the combined windows have elapsed.
- Decision: Preserve token validation before attendance-window resolution.
- Why: Existing behavior gives expired or invalid QR tokens their specific rejection reasons instead of allowing policy timing to mask token failures.

## Task 3: Close attendance → auto-mark Absent
- Decision: Store automatic Absent records with method `manual`.
- Why: The existing schema supports only QR and manual methods, and the plan explicitly permits manual for session-close records.
- Decision: Make repeated close calls safe: update the close timestamp and add only records still missing.
- Why: The spec does not define a separate already-closed error, while insert-only handling preserves every existing status and avoids duplicate records.

## Task 4: Lecturer manual statuses + audit
- Decision: Rename the domain operation to `setManualAttendance` and use a shared runtime allowlist for API validation.
- Why: The operation now sets four statuses, and one allowlist keeps the domain type and route validation aligned while excluding QR-only `present`.
- Decision: Use the generic audit action `attendance.manual_set` and retain the selected status in `newValue`.
- Why: A stable action describes the lecturer operation consistently; the structured before/after values retain the exact status transition.

## Task 5: Lecturer UI — Close + status picker
- Decision: Put the Close control in `ManualAttendancePanel` above the roster and keep it visible even when the roster is empty.
- Why: This keeps attendance mutations together and still lets a lecturer close an empty session.
- Decision: Use friendly labels for every stored roster status while preserving the enum values sent to the API.
- Why: Lecturers see readable Present/Late/Absent/Excused labels without introducing a second backend representation.

## Review fixes (from hs-review, 2026-07-18 — user chose to fix all)
- SF-2: Added a `system` value to the `attendanceRecords.method` enum (Drizzle schema + DDL) and switched auto-Absent close records from `method: "manual"` to `method: "system"`. Auto-marks are now distinguishable from genuine lecturer manual actions.
- SF-3: Extracted the DDL into `src/db/migrate.ts` and made `createDatabase` run `migrateSchema` on every connection. It creates the schema if absent and non-destructively upgrades a pre-002 database: additive `ALTER TABLE class_sections ADD COLUMN` for the policy windows, and a table rebuild of `attendance_records` when its CHECK constraints predate the new statuses/`system` method. Covered by `src/db/migrate.test.ts` (empty init, spec-001 upgrade preserving data, idempotency).
