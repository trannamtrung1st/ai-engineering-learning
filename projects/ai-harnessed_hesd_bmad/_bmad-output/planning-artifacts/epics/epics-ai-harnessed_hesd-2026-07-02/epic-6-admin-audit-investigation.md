# Epic 6: Admin Audit Investigation

Admin can browse and filter the full audit trail of check-in attempts across all sessions.

### Story 6.1: Admin Audit Log Browse and Filter

As an Admin,
I want to browse and filter check-in attempt history across all sessions,
So that I can investigate suspicious failures and verify workshop integrity after the fact.

**Acceptance Criteria:**

**Given** a signed-in Admin on `app/(admin)/audit/` (UX-DR20)
**When** they view the audit log
**Then** entries from append-only `check_in_attempts` are listed with student, session, timestamp, outcome, and failure reason when applicable (FR16, FR17)
**And** the view is read-only — no edit or delete actions in the UI (FR17, AD-11)
**When** they apply filters for session, student, date range, and outcome (UX-DR19)
**Then** results update to match the selected criteria (FR17)
**And** results are paginated at 50 rows per page (UX-DR19)
**When** reviewing failed attempts (e.g., `gps_out_of_range` cluster)
**Then** each row shows student, time, and reason code sufficient for investigation (FR17, UJ-5)
**And** Admin cannot access Instructor live session controls from this surface (UX-DR20)
**And** raw audit log export remains out of scope for MVP (FR17 non-goal)
