# Plan: Attendance reporting

**Status:** approved

**Baseline:** `npm test` -> see `.harness/specs/003-attendance-reporting/state/baseline.status` (PASS, 36 tests)

## Task 1: Make audit logs record-optional

- Spec: WHEN a CSV export completes THEN an audit entry records who exported which section and when (export events aren't tied to one attendance record)
- Files: `src/db/schema.ts`, `src/db/migrate.ts`
- Do:
  - Make `auditLogs.attendanceRecordId` nullable in schema and in the `CREATE TABLE` in migrate
  - Leave all existing audit writes (manual attendance) unchanged
- Verify: `node scripts/run-check.mjs task-1 -- npm test`

## Task 2: Seed mixed attendance history

- Spec: WHEN demo seed data is loaded THEN mixed statuses exist across more than one session
- Files: `src/db/seed.ts`
- Do:
  - Add two past class sessions (attendance opened and closed) to the demo section, keeping the existing live session untouched so check-in tests/demo still work
  - Insert resolved attendance records with mixed statuses (e.g. Linh: present, late; Minh: absent, excused) and expose new IDs on `DEMO`
- Verify: `node scripts/run-check.mjs task-2 -- npm test`

## Task 3: Student history domain query

- Spec: student sees per-session history with status or "no record", plus per-status totals; only their own
- Files: `src/domain/attendance-report.ts`, `src/domain/attendance-report.test.ts`
- Do:
  - `getStudentAttendanceHistory(db, { studentId })`: for each enrolled section, list past sessions with the student's status or `no_record`, plus per-status totals
  - Tests cover mixed statuses from seed, no-record sessions, and that a non-enrolled student gets an empty result (ownership is inherent: query keyed by studentId only)
- Verify: `node scripts/run-check.mjs task-3 -- npm test`

## Task 4: Section report domain query

- Spec: owning lecturer sees one row per enrolled student with per-status counts and attendance rate; non-owner rejected
- Files: `src/domain/attendance-report.ts`, `src/domain/attendance-report.test.ts`
- Do:
  - `getSectionReport(db, { classSectionId, lecturerId })`: throws typed error (`section_not_found` / `not_owner`) unless the lecturer owns the section; returns per-student rows with counts for all five statuses and attendance rate = (present + late + manual_present + excused) / resolved sessions
  - Tests cover counts, rate math, unresolved sessions excluded, and not_owner rejection
- Verify: `node scripts/run-check.mjs task-4 -- npm test`

## Task 5: CSV export with audit

- Spec: CSV export returns the same rows as the report; each export writes an audit entry (actor, section, timestamp)
- Files: `src/domain/attendance-report.ts`, `src/domain/attendance-report.test.ts`, `src/app/api/sections/[id]/report/export/route.ts`
- Do:
  - `exportSectionReportCsv(db, { classSectionId, lecturerId })`: reuses `getSectionReport`, renders CSV, writes an `attendance.report_exported` audit row (null `attendanceRecordId`, `newValue` describing section + row count) in a transaction
  - GET route: auth -> lecturer role -> domain call -> `text/csv` response with `Content-Disposition`, mapping domain errors to 403/404 per existing route conventions
  - Tests cover CSV content matching report rows and the audit entry fields
- Verify: `node scripts/run-check.mjs task-5 -- npm test`

## Task 6: Student history page

- Spec: logged-in student opens their attendance history; others' history unreachable
- Files: `src/app/student/history/page.tsx`, `src/app/check-in/page.tsx`
- Do:
  - Async server component: `getCurrentSession()` -> redirect to login if absent, redirect lecturers away; render per-section session list and totals from `getStudentAttendanceHistory` (own userId only)
  - Add a link to the history page from the student check-in page
- Verify: `node scripts/run-check.mjs task-6 -- npm run lint && node scripts/run-check.mjs task-6-build -- npm run build`

## Task 7: Lecturer report page

- Spec: owning lecturer views the section report on screen and can download the CSV
- Files: `src/app/lecturer/sections/[id]/report/page.tsx`, `src/app/lecturer/sessions/[id]/page.tsx`
- Do:
  - Async server component: auth + lecturer role check, call `getSectionReport` (not-owner -> render rejection/redirect), render table of students, per-status counts, attendance rate
  - Plain link/button to `/api/sections/[id]/report/export` for CSV download; link to the report from the lecturer session page
- Verify: `node scripts/run-check.mjs task-7 -- npm run lint && node scripts/run-check.mjs task-7-build -- npm run build`
