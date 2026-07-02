# Epic 2: Admin Account & Roster Management

Admin can provision all workshop participants and maintain cohort rosters before sessions.

### Story 2.1: Admin Dashboard with Quick Links

As an Admin,
I want a dashboard showing key counts and quick links to provisioning tasks,
So that I can orient myself and start workshop setup efficiently.

**Acceptance Criteria:**

**Given** a signed-in Admin
**When** they navigate to the Admin dashboard
**Then** the page displays counts for students, instructors, and rosters (UX-DR20)
**And** quick links are visible to Students list, CSV import, Instructors, and Rosters
**And** the dashboard does not expose live Workshop Session controls (Admin does not operate sessions)

### Story 2.2: Manual Student Account Provisioning

As an Admin,
I want to create a Student account manually with student_id, full_name, email, and optional initial password,
So that individual students can sign in on mobile web before a workshop.

**Acceptance Criteria:**

**Given** a signed-in Admin on the Students → Add form
**When** they submit valid student_id, full_name, email, and optional initial_password
**Then** a Student account is created via `api/src/domain/accounts/` using Supabase Auth Admin API, called from web via `lib/api-client.ts` (FR1, AD-9, AD-3, AD-15)
**And** a `profiles` row is created with `role = student` and the provided student_id
**When** they submit a duplicate student_id or email
**Then** the operation is rejected with a clear English error message
**When** the created Student signs in on mobile web
**Then** they can authenticate with email and password (FR1)

### Story 2.3: CSV Bulk Student Provisioning

As an Admin,
I want to upload a CSV to create or update many Student accounts at once,
So that I can provision an entire cohort of ~150 students efficiently.

**Acceptance Criteria:**

**Given** a signed-in Admin on Students → Import
**When** they upload a CSV with columns `student_id`, `full_name`, `email`, optional `initial_password`
**Then** the import runs via `api/src/domain/accounts/` and returns a per-row success/failure summary table (FR2, UX-DR9, UX-DR16)
**And** valid rows persist; failed rows show row-level English errors (UX-DR30)
**And** rows without `initial_password` receive a system-generated temporary password shown once in the import result (FR2)
**When** some rows fail and others succeed
**Then** successful rows are kept, failures are highlighted, and the Admin can re-upload a corrected CSV (UX-DR34)
**And** a template download link is available before upload (UX-DR16)

### Story 2.4: Instructor Account Management

As an Admin,
I want to create Instructor accounts for workshop facilitators,
So that instructors can sign in to manage sessions independently.

**Acceptance Criteria:**

**Given** a signed-in Admin on Instructors → Add
**When** they submit a valid email and display name
**Then** an Instructor account is created with `role = instructor` via `api/src/domain/accounts/` (FR4, AD-9, AD-15)
**When** the new Instructor signs in
**Then** they reach the Instructor dashboard (FR4)
**And** they cannot access Admin-only pages such as account provisioning or global audit (FR4)

### Story 2.5: Manual Cohort Roster Management

As an Admin,
I want to add, edit, or remove Students on a named Cohort Roster,
So that instructors can bind the correct student list to a workshop session.

**Acceptance Criteria:**

**Given** migrations for `cohort_rosters` and `roster_members` tables
**When** an Admin creates a named roster and adds a student by student_id
**Then** the student_id must reference an existing Student account or the add is rejected (FR5)
**When** an Admin removes a student from a roster
**Then** that student is no longer eligible for new check-ins on sessions bound to that roster (FR5)
**And** roster CRUD writes go through `api/src/domain/rosters/` via NestJS API; web calls via `lib/api-client.ts` (AD-3, AD-15)

### Story 2.6: CSV Roster Import (Append / Replace)

As an Admin,
I want to bulk add students to a roster via CSV with append or replace mode,
So that I can maintain large cohort lists without manual entry.

**Acceptance Criteria:**

**Given** a signed-in Admin on a Roster detail → Import page
**When** they choose import mode Append or Replace before uploading (UX-DR17)
**And** they upload a CSV with `student_id` and optional `cohort_label`
**Then** unknown student_id rows fail with per-row errors; valid rows are added (FR6)
**When** Append mode is selected
**Then** existing roster members not in the CSV remain unchanged (FR6)
**When** Replace mode is selected and import succeeds
**Then** roster members not present in the CSV are removed (FR6)
**And** import results display in a per-row summary table (UX-DR16, UX-DR34)
