# 2. Target User

## 2.1 Jobs To Be Done

- **Admin:** Provision student accounts and rosters before workshops without manual one-by-one entry for 150 students.
- **Instructor:** Start a session quickly, see who has checked in without calling names, fix edge cases on the spot, export attendance after class.
- **Student:** Check in in under a minute from a phone without installing an app.
- **Organizer (program):** Trust attendance data enough to report participation after each HESD cohort.

## 2.2 Non-Users (v1)

- School registrar / academic affairs staff (no integration)
- Students outside admin-provisioned accounts
- External auditors requiring school SSO or enterprise compliance certifications

## 2.3 Key User Journeys

**UJ-1. Linh provisions the cohort before workshop week**

Linh is the HESD program admin. Entry: authenticated on the Admin web dashboard. She uploads `students.csv` (student_id, full_name, email) to create 120 accounts, reviews per-row errors for 3 duplicate emails, fixes them, and re-imports. She uploads `roster-hesd-spring.csv` binding student_ids to the Spring cohort. Climax: roster count shows 120 with zero import errors. Resolution: cohort is ready for instructors to bind to sessions.

**UJ-2. Minh configures and opens a live workshop session**

Minh is the HESD instructor. Entry: authenticated on the Instructor web dashboard. He creates a Workshop Session for "HESD Day 2 — APIs", binds the Spring roster, sets geofence center to the classroom pin (default 100 m radius), and moves the session to **Active**. The QR Display view opens full-screen for projection. Climax: rotating QR visible; session status shows Active. Resolution: students can begin check-in.

**UJ-3. Trang checks in from her phone during the workshop**

Trang is a student. Entry: unauthenticated; she scans the projected QR with her phone camera. Mobile web opens the check-in URL. She signs in with admin-provisioned email/password, grants GPS permission when prompted. System validates QR token, roster, prior check-in, and geofence. Climax: success screen confirms attendance with session name and timestamp. Resolution: she puts her phone away. **Edge case:** GPS denied — clear error with instruction to enable location and retry; attempt logged.

**UJ-4. Minh handles an exception and closes the session**

Mid-session, a student's GPS fails repeatedly. Minh finds the student on the realtime dashboard (Absent / Failed), uses manual override to mark Present with a required note. After class, he ends the session (status **Closed**), exports attendance CSV, and spot-checks row count matches roster size. Climax: CSV opens in spreadsheet with one row per roster student. Resolution: session archived; audit log retains override reason.

**UJ-5. Linh reviews suspicious check-in attempts**

After the workshop, Linh opens Admin audit logs filtered by session. She sees clustered failed GPS attempts from one account. She does not change attendance (instructor owns session data) but confirms logging is sufficient for disputes. Climax: each failed attempt shows student, timestamp, failure reason. Resolution: no further action unless escalated.
