# Plan: Attendance status and policy

**Status:** approved

**Baseline:** `bash -c 'npm test && npm run lint && npm run build'` -> PASS (see `.harness/specs/002-attendance-status-policy/state/baseline.status`)

**Approach (how):** Extend the existing domain-module pattern from 001. Add section-level policy columns and expand the attendance status enum in schema + seed DDL together. Resolve Present/Late (and outside-window rejection) inside `checkIn` using injected `now`. Add a new close-attendance domain + route that auto-marks Absent. Generalize manual attendance to the four lecturer statuses with the existing audit log shape. Wire Close + status picker into the lecturer session UI already used for Manual Present.

## Task 1: Schema + seeded section policy
- Spec: policy defines present/late windows; seeded demo section has a usable non-zero policy; status enum must support Late / Absent / Excused / Manual Present
- Files: `src/db/schema.ts`, `src/db/seed.ts`, `src/db/seed.test.ts`
- Do:
  - Add `presentWindowMinutes` and `lateWindowMinutes` to `classSections` (Drizzle + raw DDL in seed)
  - Expand `attendanceRecords.status` to include `late`, `absent`, `excused` (keep `present`, `manual_present`)
  - Seed the demo section with non-zero present and late windows so Present vs Late is distinguishable
- Verify: `npx tsx src/db/seed.ts && npx vitest run src/db/seed.test.ts`

## Task 2: Check-in Present / Late / outside-window rejection
- Spec: QR check-in inside present window → Present; after present but inside late (and open) → Late; after both windows → reject with failed-attempt reason; closed attendance still rejected
- Files: `src/domain/check-in.ts`, `src/domain/check-in.test.ts`, `src/app/api/check-in/route.ts`
- Do:
  - Load the section policy; compute present/late eligibility from `attendanceOpenedAt`, window minutes, and `now` (late ends at late-window expiry or attendance close — whichever comes first)
  - On success, persist `present` or `late` (method `qr`); on outside windows, reject and record attempt with a clear reason (e.g. `outside_attendance_windows`)
  - Return the resolved status from the check-in API (stop hardcoding `"present"`)
- Verify: `npx vitest run src/domain/check-in.test.ts`

## Task 3: Close attendance → auto-mark Absent
- Spec: owning lecturer closes attendance → every enrolled student without a successful record for that session gets Absent; existing Present/Late/Manual Present/Excused unchanged; further QR check-in rejected
- Files: `src/domain/close-attendance.ts`, `src/domain/close-attendance.test.ts`, `src/app/api/sessions/[id]/close/route.ts`
- Do:
  - Add `closeAttendance` (owner check + set `attendanceClosedAt`) mirroring open/route patterns
  - Insert `absent` / method `manual` (or equivalent session-close method) only for enrolled students lacking a successful record
  - Leave existing successful statuses untouched; reject close for non-owners / missing sessions with typed errors
- Verify: `npx vitest run src/domain/close-attendance.test.ts`

## Task 4: Lecturer manual statuses + audit
- Spec: owning lecturer manually sets Manual Present, Late, Absent, or Excused; audit records actor, time, old value, new value, reason
- Files: `src/domain/manual-attendance.ts`, `src/domain/manual-attendance.test.ts`, `src/app/api/sessions/[id]/manual/route.ts`
- Do:
  - Generalize `markManualPresent` into a setter that accepts `manual_present` | `late` | `absent` | `excused`
  - Require reason; write audit `oldValue`/`newValue` inside the same transaction pattern already used
  - Accept `status` in the manual API body and map domain errors to HTTP like today
- Verify: `npx vitest run src/domain/manual-attendance.test.ts`

## Task 5: Lecturer UI — Close + status picker
- Spec: lecturer can close attendance and manually set the four statuses where the roster/manual UI already lives; roster shows the new statuses
- Files: `src/components/ManualAttendancePanel.tsx`, `src/app/lecturer/sessions/[id]/page.tsx`
- Do:
  - Add Close attendance control calling the close API
  - Replace Present-only control with a status picker (Manual Present / Late / Absent / Excused) + reason
  - Surface current roster status including Late / Absent / Excused
- Verify: `npm test && npm run lint && npm run build`
